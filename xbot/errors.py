"""Ortak hata turleri.

StopRun ve alt siniflari "programin HEMEN durmasi gerekiyor" anlamina gelir:
beklenmeyen bir sayfa, degisen arayuz, basarisiz aksiyon. Bunlar sessizce
yutulmaz; kullaniciya bildirilir ve kanit (ekran goruntusu + sayfa HTML'i)
kaydedilir.
"""

from __future__ import annotations


class XBotError(Exception):
    """Tum XBot hatalarinin atasi."""


class StopRun(XBotError):
    """Calismanin derhal durmasi gerektigini bildirir."""


class SafetyStop(StopRun):
    """CAPTCHA, giris ekrani, kisitlama vb. beklenmeyen sayfa."""

    def __init__(self, message: str, *, kind: str = "unknown", evidence=None) -> None:
        super().__init__(message)
        self.kind = kind
        self.evidence = evidence or ()


class SelectorNotFound(StopRun):
    """Beklenen arayuz ogesi bulunamadi (X arayuzu degismis olabilir)."""

    def __init__(self, message: str, *, selector: str = "", evidence=None) -> None:
        super().__init__(message)
        self.selector = selector
        self.evidence = evidence or ()


class ActionFailed(StopRun):
    """Engelleme gibi bir aksiyon dogrulanamadi."""


class BrowserError(XBotError):
    """Tarayici baslatilamadi veya kapanirken hata olustu."""


class LimitReached(XBotError):
    """Saatlik/gunluk ust sinira ulasildi (hata degil, fren)."""


class LockError(XBotError):
    """Baska bir XBot calismasi zaten surüyor."""
