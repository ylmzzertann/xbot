"""Guvenlik freni: beklenmeyen sayfalari taniyip programi durdurur.

Kural (spesifikasyon madde 3): CAPTCHA, dogrulama/supheli giris uyarisi, giris
ekrani, "hesabiniz kisitlandi" benzeri ya da beklenmeyen herhangi bir sayfa
gorulurse program HEMEN durur, ekran goruntusu kaydeder ve kullaniciya bildirir.
Asmaya veya cozmeye CALISMAZ.

classify_page() saf bir fonksiyondur (tarayici gerektirmez), bu yuzden
testlerde dogrudan kullanilir.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SafetyStop

# --- durum turleri ---
OK = "ok"
LOGIN = "login"
CAPTCHA = "captcha"
RESTRICTED = "restricted"
ERROR = "error"

#: Bu adres parcalari gorulurse oturum dusmus veya dogrulama isteniyor demektir
LOGIN_URL_PARTS = (
    "/i/flow/login",
    "/i/flow/signup",
    "/i/flow/password_reset",
    "/account/access",
    "/login",
    "/logout",
    "/oauth",
)

CAPTCHA_URL_PARTS = ("arkoselabs", "funcaptcha", "recaptcha", "/challenge")

#: Ayirt edici metinler (kisa ve genel ifadeler bilincli olarak yok: bir tweetin
#: icinde gecip yanlis alarm vermesin)
LOGIN_MARKERS = (
    "sign in to x",
    "log in to x",
    "giriş yap veya kaydol",
    "hesabına giriş yap",
    "hesabınıza giriş yapın",
    "şifreni gir",
    "enter your password",
    "yeni misin? kaydol",
)

CAPTCHA_MARKERS = (
    "captcha",
    "robot değilim",
    "i am not a robot",
    "verify you are human",
    "insan olduğunu doğrula",
    "insan olduğunuzu doğrula",
    "bu isteği sen mi yaptın",
    "doğrulama kodu gönderdik",
    "unusual login activity",
    "olağan dışı giriş",
    "şüpheli giriş",
    "suspicious login",
)

RESTRICTED_MARKERS = (
    "hesabınız kısıtlandı",
    "hesabın kısıtlandı",
    "hesabınız askıya alındı",
    "hesabın askıya alındı",
    "account is suspended",
    "account has been suspended",
    "hesabınız kilitlendi",
    "hesabın kilitlendi",
    "account has been locked",
    "temporarily restricted",
    "geçici olarak kısıtland",
    "geçici olarak engellendi",
    "you are rate limited",
    "hız sınırına ulaştın",
    "caps on the number of",
)

ERROR_MARKERS = (
    "something went wrong",
    "bir şeyler ters gitti",
    "try reloading",
    "yeniden yüklemeyi dene",
    "bu sayfa mevcut değil",
    "this page doesn't exist",
)

_MARKER_GROUPS = (
    (CAPTCHA, CAPTCHA_MARKERS),
    (RESTRICTED, RESTRICTED_MARKERS),
    (LOGIN, LOGIN_MARKERS),
    (ERROR, ERROR_MARKERS),
)

_KIND_MESSAGES = {
    LOGIN: "Giriş/oturum ekranı görüldü. Oturum düşmüş olabilir: 'login' komutuyla yeniden gir.",
    CAPTCHA: "CAPTCHA veya doğrulama ekranı görüldü. Program durdu; bunu ELLE çözmen gerekiyor.",
    RESTRICTED: "Hesap kısıtlaması/askıya alma uyarısı görüldü. Program durdu, hiçbir işlem yapılmadı.",
    ERROR: "X beklenmeyen bir hata sayfası gösterdi. Program durdu.",
}


@dataclass(frozen=True, slots=True)
class PageState:
    """Sayfanin durumu."""

    kind: str
    marker: str = ""
    detail: str = ""

    @property
    def is_ok(self) -> bool:
        return self.kind == OK

    @property
    def message(self) -> str:
        base = _KIND_MESSAGES.get(self.kind, "Beklenmeyen sayfa durumu.")
        if self.marker:
            return f"{base} (işaret: '{self.marker}')"
        return base


def classify_page(url: str, text: str = "", *, title: str = "") -> PageState:
    """Adres ve sayfa metninden durumu cikarir."""
    low_url = (url or "").lower()
    for part in CAPTCHA_URL_PARTS:
        if part in low_url:
            return PageState(CAPTCHA, part, "adres")
    for part in LOGIN_URL_PARTS:
        if part in low_url:
            return PageState(LOGIN, part, "adres")

    haystacks = [(title or "").lower(), (text or "").lower()]
    for kind, markers in _MARKER_GROUPS:
        for marker in markers:
            for haystack in haystacks:
                if marker in haystack:
                    return PageState(kind, marker, "metin")
    return PageState(OK)


def page_snapshot(page, *, max_chars: int = 20000) -> tuple[str, str, str]:
    """Sayfadan (adres, baslik, metin) alir; hata olursa bos deger doner."""
    url = ""
    title = ""
    text = ""
    try:
        url = page.url or ""
    except Exception:  # pragma: no cover - tarayici hatasi
        pass
    try:
        title = page.title() or ""
    except Exception:  # pragma: no cover
        pass
    for getter in ("inner_text", "content"):
        try:
            if getter == "inner_text":
                text = page.inner_text("body")
            else:
                text = page.content()
            break
        except Exception:  # pragma: no cover
            continue
    return url, title, (text or "")[:max_chars]


def assert_safe(page, *, session=None, context: str = "", logger=None) -> None:
    """Sayfa beklenen durumda degilse kanit kaydedip SafetyStop yukseltir."""
    url, title, text = page_snapshot(page)
    state = classify_page(url, text, title=title)
    if state.is_ok:
        return
    evidence: tuple = ()
    if session is not None:
        evidence = session.save_evidence(f"durdu-{state.kind}")
    message = state.message
    if context:
        message = f"{context}: {message}"
    if logger is not None:
        logger.error("%s  (adres: %s)", message, url)
        for path in evidence:
            logger.error("Kanıt kaydedildi: %s", path)
    raise SafetyStop(message, kind=state.kind, evidence=evidence)
