"""Uygulama katmani: parcalari birlestirir.

cli.py sadece ekrana yazdirir; gercek isler burada kurulur. Boylece ayni isler
ileride baska bir arayuzden (web paneli, Telegram botu) de cagrilabilir.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import selectors
from .actions import BlockOutcome, Blocker, PlaywrightBlockUi
from .browser import BrowserSession, find_first
from .detector.engine import DecisionEngine
from .errors import SafetyStop, StopRun
from .logging_setup import get_logger, setup_logging_from_config
from .models import Decision, Tweet
from .notify import notify, write_error_file
from .ratelimit import RateLimiter
from .runner import Runner, RunSummary
from .scraper import PlaywrightTweetSource, ScrapeResult, SearchScraper
from .storage import Storage
from .timefilter import TimeWindow
from .whitelist import Whitelist

LOCK_FILE_NAME = "xbot.lock"


def make_notifier(config, logger=None):
    """Hata bildirimi gonderen fonksiyon uretir."""
    log = logger or get_logger("notify")

    def _notifier(title: str, message: str) -> None:
        if config.notifications.error_file and config.paths is not None:
            write_error_file(config.paths.log_dir, title, message)
        notify(title, message, enabled=config.notifications.desktop, logger=log)

    return _notifier


@dataclass
class AppServices:
    """Tarayici gerektirmeyen cekirdek parcalar."""

    config: object
    logger: object
    storage: Storage
    engine: DecisionEngine
    whitelist: Whitelist
    limiter: RateLimiter
    notifier: object = None

    @property
    def lock_path(self) -> Path:
        return Path(self.config.paths.log_dir) / LOCK_FILE_NAME

    def close(self) -> None:
        self.storage.close()

    def __enter__(self) -> "AppServices":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def build_services(config, *, console_log: bool = True) -> AppServices:
    """Ayarlardan calisir durumda bir servis kumesi kurar."""
    config.ensure_dirs()
    logger = setup_logging_from_config(config, console=console_log)
    storage = Storage(config.paths.db_path)
    storage.connect()
    engine = DecisionEngine.from_config(config)
    whitelist = Whitelist.from_file(config.files.whitelist, logger=logger)
    limiter = RateLimiter(
        config.limits, config.delays, storage=storage, logger=get_logger("limit")
    )
    return AppServices(
        config=config,
        logger=logger,
        storage=storage,
        engine=engine,
        whitelist=whitelist,
        limiter=limiter,
        notifier=make_notifier(config, logger),
    )


# --------------------------------------------------------------------------
# tarayici gerektiren isler
# --------------------------------------------------------------------------


@dataclass
class SelectorCheckResult:
    """check-selectors komutunun tek satirlik sonucu."""

    name: str
    selector: str
    required: bool
    found: int
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.found > 0 or not self.required


class BrowserApp:
    """Tarayici acan isler: login, tarama, engelleme, beyaz liste senkronu."""

    def __init__(self, services: AppServices, *, headless: bool | None = None) -> None:
        self.services = services
        self.config = services.config
        self.logger = services.logger
        self.session = BrowserSession(
            services.config, headless=headless, logger=get_logger("browser")
        )

    # --- yasam dongusu ---

    def __enter__(self) -> "BrowserApp":
        self.session.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.session.stop()

    @property
    def page(self):
        return self.session.page

    # --- giris ---

    def wait_for_manual_login(self, *, timeout_seconds: int = 300, tick: int = 3) -> bool:
        """Kullanici elle giris yapana kadar bekler (sifre sorulmaz, yazilmaz)."""
        self.session.goto(selectors.HOME_URL, context="giriş sayfası")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.session.is_logged_in():
                return True
            time.sleep(tick)
        return False

    def ensure_logged_in(self) -> None:
        """Oturum yoksa durur (login komutuna yonlendirir)."""
        if self.session.is_logged_in():
            return
        raise SafetyStop(
            "Oturum açık değil. Şunu çalıştır ve tarayıcıda elle giriş yap:\n"
            "    python -m xbot login",
            kind="login",
        )

    def detect_handle(self) -> str:
        """Ayardaki ya da sayfadaki kullanici adini dondurur."""
        if self.config.account_handle:
            return self.config.account_handle
        return self.session.detect_handle() or ""

    # --- arama sayfasi ---

    def open_search(self, query: str) -> None:
        """Arama sayfasini 'Son' sekmesinde acar ve sonuclari bekler."""
        url = selectors.search_url(query, latest=True)
        self.session.goto(url, context=f"'{query}' arama sayfası")
        self.ensure_logged_in()
        deadline = time.monotonic() + self.config.browser.timeout_seconds
        while time.monotonic() < deadline:
            if find_first(self.page, selectors.CHAINS["tweet"]) is not None:
                return
            if find_first(self.page, (selectors.EMPTY_STATE,)) is not None:
                self.logger.info("'%s' için sonuç bulunamadı.", query)
                return
            time.sleep(1)
        # Ne tweet ne de "sonuc yok" geldi: arayuz degismis olabilir
        from .browser import require_first

        require_first(
            self.page,
            selectors.CHAINS["tweet"],
            what=f"'{query}' arama sonuçları",
            session=self.session,
            logger=self.logger,
        )

    def make_scrape(self):
        """Runner'a verilecek tarama fonksiyonunu uretir."""

        def _scrape(query: str, window: TimeWindow) -> ScrapeResult:
            self.open_search(query)
            source = PlaywrightTweetSource(
                self.page,
                session=self.session,
                delays=self.services.limiter,
                logger=get_logger("scraper"),
            )
            scraper = SearchScraper(
                source,
                max_scrolls=self.config.max_scrolls_per_query,
                logger=get_logger("scraper"),
            )
            return scraper.scrape(query, window)

        return _scrape

    def make_blocker(self, *, dry_run: bool) -> Blocker:
        ui = PlaywrightBlockUi(
            self.page,
            session=self.session,
            logger=get_logger("actions"),
            timeout_ms=self.config.browser.timeout_seconds * 1000,
        )
        return Blocker(
            ui,
            storage=self.services.storage,
            whitelist=self.services.whitelist,
            limiter=self.services.limiter,
            dry_run=dry_run,
            logger=get_logger("actions"),
        )

    # --- ana is: tarama turu ---

    def run(
        self,
        *,
        auto: bool,
        queries: Sequence[str] | None = None,
        minutes: int | None = None,
    ) -> RunSummary:
        window = TimeWindow.last_minutes(minutes or self.config.time_window_minutes)
        runner = Runner(
            self.config,
            engine=self.services.engine,
            storage=self.services.storage,
            whitelist=self.services.whitelist,
            limiter=self.services.limiter,
            blocker=self.make_blocker(dry_run=not auto),
            scrape=self.make_scrape(),
            logger=get_logger("runner"),
            notifier=self.services.notifier,
        )
        return runner.run(auto=auto, queries=queries, window=window)

    # --- review: tek tweet engelleme ---

    def block_single(self, tweet: Tweet, decision: Decision) -> BlockOutcome:
        """Tweetin kendi sayfasina gidip hesabi engeller (review komutu icin)."""
        self.session.goto(tweet.permalink, context=f"@{tweet.username} tweet sayfası")
        self.ensure_logged_in()
        blocker = self.make_blocker(dry_run=False)
        return blocker.block(tweet, decision, mode="review")

    # --- secici dogrulama ---

    def check_selectors(
        self, query: str, *, with_menu: bool = False
    ) -> list[SelectorCheckResult]:
        """Canli sayfada her seciciyi dener ve kac tane bulundugunu bildirir."""
        self.open_search(query)
        results: list[SelectorCheckResult] = []
        for check in selectors.SEARCH_PAGE_CHECKS:
            count = 0
            try:
                count = self.page.locator(check.selector).count()
            except Exception as exc:  # pragma: no cover
                self.logger.debug("Seçici denenemedi (%s): %s", check.selector, exc)
            results.append(
                SelectorCheckResult(
                    check.name, check.selector, check.required, count, check.note
                )
            )

        if with_menu:
            results.extend(self._check_menu_selectors())
        return results

    def _check_menu_selectors(self) -> list[SelectorCheckResult]:
        """'...' menusunu acar, menu secicilerini dogrular ve Escape ile kapatir.

        ENGELLEME YAPMAZ: sadece menunun icerigini kontrol eder.
        """
        out: list[SelectorCheckResult] = []
        found = find_first(self.page, selectors.CHAINS["tweet"])
        if found is None:
            return [
                SelectorCheckResult(
                    "Menü kontrolü", selectors.TWEET, True, 0, "tweet bulunamadı"
                )
            ]
        article = found[1]
        menu_button = find_first(article, selectors.CHAINS["menu_button"])
        if menu_button is None:
            return [
                SelectorCheckResult(
                    '"..." menü düğmesi', selectors.TWEET_MENU_BUTTON, True, 0
                )
            ]
        try:
            menu_button[1].click(timeout=self.config.browser.timeout_seconds * 1000)
            time.sleep(1)
            for check in selectors.MENU_CHECKS:
                count = 0
                try:
                    count = self.page.locator(check.selector).count()
                except Exception:  # pragma: no cover
                    pass
                out.append(
                    SelectorCheckResult(
                        check.name, check.selector, check.required, count, check.note
                    )
                )
        finally:
            try:
                self.page.keyboard.press("Escape")
            except Exception:  # pragma: no cover
                pass
        return out

    # --- beyaz liste senkronu ---

    def collect_following(
        self, handle: str, *, max_scrolls: int = 30
    ) -> list[str]:
        """Takip edilen hesaplarin kullanici adlarini toplar."""
        self.session.goto(
            selectors.following_url(handle), context=f"@{handle} takip listesi"
        )
        self.ensure_logged_in()
        seen: list[str] = []
        known: set[str] = set()
        empty_rounds = 0
        for _ in range(max_scrolls):
            links = self.page.locator(selectors.USER_CELL_LINK)
            added = 0
            for index in range(links.count()):
                href = links.nth(index).get_attribute("href") or ""
                name = href.strip("/").split("/")[0]
                if not name or "/" in name or name.lower() in known:
                    continue
                known.add(name.lower())
                seen.append(name)
                added += 1
            if added == 0:
                empty_rounds += 1
                if empty_rounds >= 2:
                    break
            else:
                empty_rounds = 0
            try:
                self.page.mouse.wheel(0, 1600)
            except Exception:  # pragma: no cover
                self.page.keyboard.press("PageDown")
            self.services.limiter.wait_between_scrolls()
        return seen


__all__ = [
    "AppServices",
    "BrowserApp",
    "SelectorCheckResult",
    "StopRun",
    "build_services",
    "make_notifier",
]
