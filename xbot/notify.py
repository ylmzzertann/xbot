"""Masaustu bildirimi (hata durumunda haber vermek icin).

Zamanlanmis gorevle calisirken program durursa (CAPTCHA, degisen arayuz vb.)
kullanicinin bunu fark etmesi gerekir. Ek paket gerektirmeyen yollar denenir:

  Windows : user32.MessageBoxTimeoutW (belirli sure sonra kendi kapanir)
  macOS   : osascript ile bildirim
  Linux   : notify-send

Hicbiri olmazsa bildirim sessizce atlanir; olay zaten loglara ve
logs/SON_HATA.txt dosyasina yazilir.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .logging_setup import get_logger

ERROR_FILE_NAME = "SON_HATA.txt"
_TIMEOUT_MS = 60_000


def _notify_windows(title: str, message: str) -> bool:
    import ctypes

    try:
        user32 = ctypes.windll.user32
        # MB_OK | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
        flags = 0x00 | 0x30 | 0x10000 | 0x40000
        if hasattr(user32, "MessageBoxTimeoutW"):
            user32.MessageBoxTimeoutW(None, message, title, flags, 0, _TIMEOUT_MS)
        else:  # pragma: no cover - cok eski Windows
            user32.MessageBoxW(None, message, title, flags)
        return True
    except Exception:  # pragma: no cover
        return False


def _notify_macos(title: str, message: str) -> bool:  # pragma: no cover - platform
    if not shutil.which("osascript"):
        return False
    safe_title = title.replace('"', "'")
    safe_message = message.replace('"', "'")
    script = f'display notification "{safe_message}" with title "{safe_title}"'
    return subprocess.run(["osascript", "-e", script], check=False).returncode == 0


def _notify_linux(title: str, message: str) -> bool:  # pragma: no cover - platform
    if not shutil.which("notify-send"):
        return False
    return subprocess.run(["notify-send", title, message], check=False).returncode == 0


def notify(title: str, message: str, *, enabled: bool = True, logger=None) -> bool:
    """Masaustu bildirimi gonderir. Basarili olursa True."""
    log = logger or get_logger("notify")
    if not enabled:
        log.debug("Masaüstü bildirimi kapalı, atlandı.")
        return False
    short = message if len(message) <= 500 else message[:497] + "..."
    try:
        if sys.platform.startswith("win"):
            sent = _notify_windows(title, short)
        elif sys.platform == "darwin":
            sent = _notify_macos(title, short)
        else:
            sent = _notify_linux(title, short)
    except Exception as exc:  # pragma: no cover
        log.debug("Bildirim gönderilemedi: %s", exc)
        return False
    if not sent:
        log.debug("Bildirim yolu bulunamadı (atlandı).")
    return sent


def write_error_file(log_dir: str | Path, title: str, message: str) -> Path | None:
    """Son hatayi logs/SON_HATA.txt dosyasina yazar (bildirim yedegi)."""
    try:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ERROR_FILE_NAME
        stamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        path.write_text(f"[{stamp}] {title}\n\n{message}\n", encoding="utf-8")
        return path
    except OSError:  # pragma: no cover
        return None
