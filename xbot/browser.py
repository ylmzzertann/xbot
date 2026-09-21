"""Playwright oturumu ve profil yonetimi.

Oturum "kalici profil" (persistent context) ile tutulur: bir kez elle giris
yapilir, cerezler config.yaml -> paths.profile_dir klasorunde kalir. Kod hicbir
yere sifre/token yazmaz, sormaz, okumaz.

Bot algilamayi atlatmaya yonelik HICBIR teknik yok (stealth eklentisi, parmak
izi gizleme, proxy, otomasyon bayragi kapatma vb.). Sadece makul bekleme ve
limitler kullanilir.

playwright paketi yalnizca gercekten tarayici gerektigi anda ice aktarilir;
boylece tespit tarafi (Asama 1) playwright kurulu olmadan da calisir.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import BrowserError, SelectorNotFound
from .logging_setup import get_logger
from .safety import assert_safe

DEFAULT_VIEWPORT = {"width": 1280, "height": 900}


def _import_playwright():
    """playwright'i ice aktarir; kurulu degilse anlasilir Turkce hata verir."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - kurulum hatasi
        raise BrowserError(
            "Playwright kurulu değil. Şu iki komutu çalıştır:\n"
            "    python -m pip install playwright\n"
            "    python -m playwright install chromium"
        ) from exc
    return sync_playwright


class BrowserSession:
    """Tarayiciyi acar, kapatir ve kanit (ekran goruntusu/HTML) kaydeder."""

    def __init__(self, config, *, headless: bool | None = None, logger=None) -> None:
        self.config = config
        self.logger = logger or get_logger("browser")
        self.headless = config.headless if headless is None else headless
        self._playwright = None
        self._context = None
        self._page = None

    # --- yasam dongusu ---

    def start(self):
        """Kalici profille tarayiciyi acar ve ilk sekmeyi dondurur."""
        if self._page is not None:
            return self._page
        sync_playwright = _import_playwright()
        profile_dir = Path(self.config.paths.profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(
            "Tarayıcı açılıyor (%s). Profil: %s",
            "gizli/headless" if self.headless else "görünür",
            profile_dir,
        )
        self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": str(profile_dir),
            "headless": self.headless,
            "viewport": DEFAULT_VIEWPORT,
            "locale": self.config.browser.locale,
            "args": ["--window-size=1280,900"],
        }
        if self.config.browser.channel:
            launch_kwargs["channel"] = self.config.browser.channel
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                **launch_kwargs
            )
        except Exception as exc:  # pragma: no cover - tarayici kurulum hatasi
            self.stop()
            raise BrowserError(
                "Tarayıcı başlatılamadı. Chromium kurulu mu?\n"
                "    python -m playwright install chromium\n"
                f"Ayrıntı: {exc}"
            ) from exc
        self._context.set_default_timeout(self.config.browser.timeout_seconds * 1000)
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        return self._page

    @property
    def page(self):
        if self._page is None:
            raise BrowserError("Tarayıcı henüz açılmadı (start() çağrılmadı).")
        return self._page

    @property
    def is_open(self) -> bool:
        return self._page is not None

    def stop(self) -> None:
        """Tarayiciyi ve playwright surecini kapatir."""
        for closer in (self._context, self._playwright):
            if closer is None:
                continue
            try:
                closer.close() if hasattr(closer, "close") else None
            except Exception as exc:  # pragma: no cover
                self.logger.debug("Kapatma sırasında hata yok sayıldı: %s", exc)
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # pragma: no cover
                pass
        self._context = None
        self._playwright = None
        self._page = None

    close = stop

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, *_exc_info) -> None:
        self.stop()

    # --- gezinme ---

    def goto(self, url: str, *, wait_ms: int | None = None, context: str = "") -> None:
        """Adrese gider ve sayfanin beklenen durumda oldugunu dogrular."""
        timeout = (wait_ms or self.config.browser.timeout_seconds * 1000)
        self.logger.debug("Gidiliyor: %s", url)
        try:
            self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        except Exception as exc:
            evidence = self.save_evidence("sayfa-acilmadi")
            raise BrowserError(
                f"Sayfa açılamadı: {url}\nAyrıntı: {exc}\nKanıt: {', '.join(map(str, evidence))}"
            ) from exc
        assert_safe(self.page, session=self, context=context or url, logger=self.logger)

    # --- giris durumu ---

    def is_logged_in(self) -> bool:
        """Oturum acik mi? (yan menudeki hesap dugmesine bakar)"""
        from . import selectors

        for selector in (selectors.ACCOUNT_SWITCHER, selectors.SIDE_NAV_HOME):
            try:
                if self.page.locator(selector).count() > 0:
                    return True
            except Exception:  # pragma: no cover
                continue
        return False

    def detect_handle(self) -> str | None:
        """Giris yapilmis hesabin kullanici adini bulmaya calisir."""
        from . import selectors

        try:
            element = self.page.locator(selectors.ACCOUNT_SWITCHER).first
            if element.count() == 0:
                return None
            text = element.inner_text(timeout=3000)
        except Exception:  # pragma: no cover
            return None
        for part in (text or "").replace("\n", " ").split():
            if part.startswith("@") and len(part) > 1:
                return part.lstrip("@")
        return None

    # --- kanit ---

    def _evidence_path(self, label: str, suffix: str) -> Path:
        directory = Path(self.config.paths.screenshot_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)
        return directory / f"{stamp}-{safe_label}{suffix}"

    def screenshot(self, label: str = "ekran") -> Path | None:
        """Tam sayfa ekran goruntusu kaydeder."""
        if self._page is None:
            return None
        path = self._evidence_path(label, ".png")
        try:
            self._page.screenshot(path=str(path), full_page=False)
        except Exception as exc:  # pragma: no cover
            self.logger.warning("Ekran görüntüsü alınamadı: %s", exc)
            return None
        return path

    def dump_html(self, label: str = "sayfa") -> Path | None:
        """Sayfanin HTML'ini kaydeder (seçici hata ayıklaması için)."""
        if self._page is None:
            return None
        path = self._evidence_path(label, ".html")
        try:
            path.write_text(self._page.content(), encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            self.logger.warning("Sayfa HTML'i kaydedilemedi: %s", exc)
            return None
        return path

    def save_evidence(self, label: str = "kanit") -> tuple[Path, ...]:
        """Ekran goruntusu + HTML birlikte kaydeder."""
        paths = [self.screenshot(label), self.dump_html(label)]
        saved = tuple(p for p in paths if p is not None)
        for path in saved:
            self.logger.info("Kanıt kaydedildi: %s", path)
        return saved


# --------------------------------------------------------------------------
# secici yardimcilari (tarayicidan bagimsiz test edilebilir)
# --------------------------------------------------------------------------


def find_first(
    scope, chain: Sequence[str], *, require_visible: bool = False
) -> tuple[str, Any] | None:
    """Zincirdeki ilk eslesen seciciyi ve ogeyi dondurur (beklemeden).

    require_visible=True verilirse gizli (display:none) ogeler atlanir; acilmasi
    gereken menu/onay penceresi ararken bu gerekir.
    """
    for selector in chain:
        try:
            locator = scope.locator(selector)
            if locator.count() <= 0:
                continue
            element = locator.first
            if require_visible:
                try:
                    if not element.is_visible():
                        continue
                except AttributeError:  # test sahtelerinde is_visible yok
                    pass
            return selector, element
        except Exception:  # pragma: no cover - gecersiz secici
            continue
    return None


def require_first(
    scope,
    chain: Sequence[str],
    *,
    what: str,
    session: BrowserSession | None = None,
    logger=None,
    require_visible: bool = False,
) -> tuple[str, Any]:
    """find_first ama bulunamazsa SelectorNotFound yukseltir (+ kanit kaydeder)."""
    found = find_first(scope, chain, require_visible=require_visible)
    if found is not None:
        return found
    evidence: tuple = ()
    if session is not None:
        evidence = session.save_evidence(f"secici-yok-{what}")
    message = (
        f"Arayüz öğesi bulunamadı: {what}. X arayüzü değişmiş olabilir.\n"
        f"Denenen seçiciler: {', '.join(chain)}\n"
        "Düzeltmek için: xbot/selectors.py dosyasını güncelle "
        "(yardım için 'python -m xbot check-selectors')."
    )
    if evidence:
        message += "\nKanıt: " + ", ".join(str(p) for p in evidence)
    if logger is not None:
        logger.error(message)
    raise SelectorNotFound(message, selector=chain[0] if chain else "", evidence=evidence)


def wait_for_first(
    page,
    chain: Sequence[str],
    *,
    what: str,
    timeout_ms: int = 15000,
    session: BrowserSession | None = None,
    logger=None,
) -> str:
    """Zincirdeki secicilerden biri gorunene kadar bekler."""
    per_selector = max(1000, timeout_ms // max(1, len(chain)))
    for selector in chain:
        try:
            page.wait_for_selector(selector, timeout=per_selector, state="visible")
            return selector
        except Exception:
            continue
    return require_first(page, chain, what=what, session=session, logger=logger)[0]
