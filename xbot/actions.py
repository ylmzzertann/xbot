"""Engelleme aksiyonu.

Akis (X arayuzu): tweetin "..." menusu -> "Engelle" -> onay penceresi -> "Engelle".

Her adimda beklenen ogenin GERCEKTEN geldigi dogrulanir; gelmezse program durur
(SelectorNotFound / ActionFailed) ve kanit kaydedilir. Sessizce devam etmek yok.

DOM islemleri BlockUi arayuzunun arkasinda tutulur; Blocker sinifi (limitler,
beyaz liste, kayitlar) tarayici olmadan test edilebilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from collections.abc import Sequence

from . import selectors
from .browser import find_first, require_first, wait_for_first
from .errors import ActionFailed, SafetyStop
from .logging_setup import get_logger
from .models import Decision, Tweet
from .safety import NOT_FOUND, assert_safe

# --- sonuc durumlari ---
STATUS_BLOCKED = "blocked"
STATUS_DRY_RUN = "dry-run"
STATUS_WHITELISTED = "whitelisted"
STATUS_ALREADY = "already"
STATUS_LIMIT = "limit"
STATUS_SKIPPED = "skipped"
STATUS_NOT_FOUND = "not-found"  # tweet silinmis: sadece bu hesap atlandi


@dataclass(frozen=True, slots=True)
class BlockOutcome:
    """Bir engelleme denemesinin sonucu."""

    status: str
    username: str
    tweet_id: str
    message: str
    record_id: int | None = None

    @property
    def blocked(self) -> bool:
        return self.status == STATUS_BLOCKED

    @property
    def would_block(self) -> bool:
        return self.status == STATUS_DRY_RUN


class BlockUi(Protocol):
    """Engelleme icin gereken en kucuk arayuz."""

    def open_tweet_menu(self, tweet_id: str, url: str | None = None) -> None: ...

    def click_block(self) -> None: ...

    def confirm_block(self) -> None: ...

    def verify_blocked(self, username: str) -> bool: ...

    def close_menu(self) -> None: ...


# --------------------------------------------------------------------------
# gercek (Playwright) arayuz
# --------------------------------------------------------------------------


class PlaywrightBlockUi:
    """X arayuzunde engelleme adimlarini uygular."""

    def __init__(self, page, *, session=None, logger=None, timeout_ms: int = 10000) -> None:
        self.page = page
        self.session = session
        self.logger = logger or get_logger("actions")
        self.timeout_ms = timeout_ms

    def _check_page(self, context: str) -> None:
        assert_safe(self.page, session=self.session, context=context, logger=self.logger)

    def _click(self, element, what: str) -> None:
        """Tiklar; tiklanamazsa anlasilir Turkce hata verir ve kanit kaydeder."""
        try:
            element.click(timeout=self.timeout_ms)
        except Exception as exc:
            evidence: tuple = ()
            if self.session is not None:
                evidence = self.session.save_evidence(f"tiklanamadi-{what}")
            detail = f"{what} tıklanamadı (görünmüyor veya değişmiş olabilir)."
            detail += f"\nAyrıntı: {exc}"
            if evidence:
                detail += "\nKanıt: " + ", ".join(str(path) for path in evidence)
            raise ActionFailed(detail) from exc

    def open_tweet_menu(self, tweet_id: str, url: str | None = None) -> None:
        """Tweeti bulur, '...' dugmesine basar, menunun acildigini dogrular.

        X zaman tunelini "sanallastirir": asagi kaydirildikca ustteki tweetler
        sayfadan silinir. Tweet o an sayfada yoksa ve adresi biliniyorsa,
        tweetin kendi sayfasina gidilir.
        """
        chain = selectors.tweet_chain_by_id(tweet_id)
        if url and self.session is not None and find_first(self.page, chain) is None:
            self.logger.info("Tweet sayfada görünmüyor, kendi sayfası açılıyor: %s", url)
            self.session.goto(url, context="engellenecek tweetin sayfası")
            wait_for_first(
                self.page,
                chain,
                what=f"engellenecek tweet ({tweet_id})",
                timeout_ms=self.timeout_ms,
                session=self.session,
                logger=self.logger,
            )
        self._check_page("engelleme öncesi sayfa kontrolü")
        _selector, article = require_first(
            self.page,
            selectors.tweet_chain_by_id(tweet_id),
            what=f"engellenecek tweet ({tweet_id})",
            session=self.session,
            logger=self.logger,
        )
        try:
            article.scroll_into_view_if_needed(timeout=self.timeout_ms)
        except Exception:  # pragma: no cover - kaydirma basarisiz olabilir
            pass
        _menu_selector, menu_button = require_first(
            article,
            selectors.CHAINS["menu_button"],
            what='tweet "..." menü düğmesi',
            session=self.session,
            logger=self.logger,
        )
        self._click(menu_button, 'tweet "..." menü düğmesi')
        wait_for_first(
            self.page,
            selectors.CHAINS["dropdown"],
            what="açılan menü",
            timeout_ms=self.timeout_ms,
            session=self.session,
            logger=self.logger,
        )

    def click_block(self) -> None:
        """Menudeki 'Engelle' satirina basar ve onay penceresini bekler."""
        _selector, dropdown = require_first(
            self.page,
            selectors.CHAINS["dropdown"],
            what="açılan menü",
            session=self.session,
            logger=self.logger,
            require_visible=True,
        )
        _block_selector, block_item = require_first(
            dropdown,
            selectors.CHAINS["menu_block"],
            what='menüdeki "Engelle" satırı',
            session=self.session,
            logger=self.logger,
        )
        self._click(block_item, 'menüdeki "Engelle" satırı')
        wait_for_first(
            self.page,
            (selectors.CONFIRM_SHEET, *selectors.CHAINS["confirm"]),
            what="engelleme onay penceresi",
            timeout_ms=self.timeout_ms,
            session=self.session,
            logger=self.logger,
        )

    def confirm_block(self) -> None:
        """Onay penceresindeki 'Engelle' dugmesine basar."""
        _selector, button = require_first(
            self.page,
            selectors.CHAINS["confirm"],
            what="onay penceresindeki Engelle düğmesi",
            session=self.session,
            logger=self.logger,
            require_visible=True,
        )
        self._click(button, "onay penceresindeki Engelle düğmesi")

    def verify_blocked(self, username: str) -> bool:
        """Onay penceresinin kapandigini (islemin gerceklestigini) dogrular."""
        try:
            self.page.wait_for_selector(
                selectors.CONFIRM_SHEET, state="hidden", timeout=self.timeout_ms
            )
        except Exception:
            return False
        self._check_page("engelleme sonrası sayfa kontrolü")
        return True

    def close_menu(self) -> None:
        """Acik menu/pencere varsa Escape ile kapatir."""
        try:
            self.page.keyboard.press("Escape")
        except Exception:  # pragma: no cover
            pass


# --------------------------------------------------------------------------
# karar + kayit katmani
# --------------------------------------------------------------------------


class Blocker:
    """Engelleme kurallarini uygular: beyaz liste, tekrar, limit, kayit."""

    def __init__(
        self,
        ui: BlockUi | None,
        *,
        storage,
        whitelist,
        limiter,
        dry_run: bool = True,
        tweet_log=None,
        logger=None,
    ) -> None:
        self.ui = ui
        self.storage = storage
        self.whitelist = whitelist
        self.limiter = limiter
        self.dry_run = dry_run
        self.tweet_log = tweet_log  # engellenenlerin tweetlerini tutan dosya
        self.logger = logger or get_logger("actions")

    def block(
        self,
        tweet: Tweet,
        decision: Decision,
        *,
        mode: str = "auto",
        evidence_tweets: Sequence[Tweet] | None = None,
        reason: str | None = None,
    ) -> BlockOutcome:
        """Tek bir hesabi engeller (ya da neden engellemedigini soyler).

        evidence_tweets: dosyaya yazilacak tweetler (varsayilan: sadece bu tweet).
        reason: kayitlarda gorunecek kural (varsayilan: kararin kurallari).
        """
        username = tweet.username
        rule_text = reason or decision.rule_summary or "-"

        if self.whitelist is not None and self.whitelist.contains(username):
            message = f"@{username} beyaz listede: engellenmedi."
            self.logger.info(message)
            return BlockOutcome(STATUS_WHITELISTED, username, tweet.tweet_id, message)

        if self.storage is not None and self.storage.is_blocked(username):
            message = f"@{username} daha önce engellenmiş: tekrar işlem yapılmadı."
            self.logger.info(message)
            return BlockOutcome(STATUS_ALREADY, username, tweet.tweet_id, message)

        if self.limiter is not None:
            status = self.limiter.status()
            if not status.allowed:
                self.logger.warning(status.reason)
                return BlockOutcome(
                    STATUS_LIMIT, username, tweet.tweet_id, status.reason
                )

        if self.dry_run:
            message = (
                f"[dry-run] @{username} ENGELLENİRDİ "
                f"(kural: {rule_text}) {tweet.permalink}"
            )
            self.logger.info(message)
            return BlockOutcome(STATUS_DRY_RUN, username, tweet.tweet_id, message)

        if self.ui is None:
            raise ActionFailed("Engelleme arayüzü yok (tarayıcı açılmamış).")

        self.logger.warning(
            "ENGELLENİYOR: @%s (kural: %s) %s",
            username,
            rule_text,
            tweet.permalink,
        )
        try:
            self.ui.open_tweet_menu(tweet.tweet_id, url=tweet.permalink)
        except SafetyStop as exc:
            if exc.kind != NOT_FOUND:
                raise
            message = f"@{username}: tweet bulunamadı (silinmiş olabilir), atlandı."
            self.logger.warning(message)
            return BlockOutcome(STATUS_NOT_FOUND, username, tweet.tweet_id, message)
        self.ui.click_block()
        self.ui.confirm_block()
        if not self.ui.verify_blocked(username):
            self.ui.close_menu()
            raise ActionFailed(
                f"@{username} engellendi mi doğrulanamadı: onay penceresi kapanmadı. "
                "Program durduruldu; hesabı elle kontrol et."
            )

        record_id = None
        if self.storage is not None:
            record_id = self.storage.record_block(
                tweet, decision, mode=mode, rules=rule_text
            )
        if self.limiter is not None:
            self.limiter.register_block()
        if self.tweet_log is not None:
            try:
                self.tweet_log.append(
                    list(evidence_tweets) if evidence_tweets else [tweet],
                    reason=rule_text,
                    mode=mode,
                )
            except OSError as exc:  # engelleme oldu; dosya yazilamadi diye durma
                self.logger.error("Tweet dosyasına yazılamadı: %s", exc)
        message = f"@{username} engellendi (kural: {rule_text})."
        self.logger.warning(message)
        if self.limiter is not None:
            self.limiter.wait_between_actions()
        return BlockOutcome(
            STATUS_BLOCKED, username, tweet.tweet_id, message, record_id=record_id
        )
