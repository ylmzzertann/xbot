"""Kilit dosyasi: ayni anda iki XBot calismasi olmasin (madde 7).

Zamanlanmis gorev ile elle baslatma cakisirsa ikinci calisma baslamaz. Kilit
dosyasinda surec numarasi (PID) ve baslama zamani durur; surec olmediyse veya
kilit cok yaslandiysa "bayat" sayilip temizlenir.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .errors import LockError
from .logging_setup import get_logger

#: Bu kadar saat gecmis bir kilit, sureci kontrol edilemese bile bayat sayilir
DEFAULT_STALE_HOURS = 3


def pid_alive(pid: int) -> bool:
    """Surec hala yasiyor mu? (Windows ve POSIX)"""
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:  # pragma: no cover - POSIX
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunLock:
    """with RunLock(path): ... seklinde kullanilir."""

    def __init__(
        self,
        path: str | Path,
        *,
        stale_hours: int = DEFAULT_STALE_HOURS,
        logger=None,
    ) -> None:
        self.path = Path(path)
        self.stale_hours = stale_hours
        self.logger = logger or get_logger("lock")
        self._acquired = False

    # --- ic yardimcilar ---

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _is_stale(self, data: dict) -> tuple[bool, str]:
        pid = int(data.get("pid", 0) or 0)
        started = data.get("started_at", "")
        if pid and not pid_alive(pid):
            return True, f"kilidi tutan süreç (PID {pid}) artık çalışmıyor"
        try:
            moment = datetime.fromisoformat(started)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
        except ValueError:
            return True, "kilit dosyası okunamadı"
        if datetime.now(timezone.utc) - moment > timedelta(hours=self.stale_hours):
            return True, f"kilit {self.stale_hours} saatten eski"
        return False, ""

    def _write(self) -> None:
        payload = {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME", ""),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)

    # --- genel arayuz ---

    def acquire(self) -> "RunLock":
        try:
            self._write()
        except FileExistsError:
            data = self._read()
            stale, why = self._is_stale(data)
            if not stale:
                raise LockError(
                    "Başka bir XBot çalışması sürüyor "
                    f"(PID {data.get('pid', '?')}, başlangıç {data.get('started_at', '?')}).\n"
                    f"Gerçekten çalışmıyorsa şu dosyayı sil: {self.path}"
                ) from None
            self.logger.warning("Bayat kilit temizlendi (%s): %s", why, self.path)
            try:
                self.path.unlink()
            except OSError as exc:  # pragma: no cover
                raise LockError(f"Bayat kilit silinemedi: {self.path} ({exc})") from exc
            try:
                self._write()
            except FileExistsError as exc:  # pragma: no cover - yaris durumu
                raise LockError(
                    f"Kilit alınamadı, başka bir çalışma araya girdi: {self.path}"
                ) from exc
        self._acquired = True
        self.logger.debug("Kilit alındı: %s", self.path)
        return self

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:  # pragma: no cover
            self.logger.warning("Kilit dosyası silinemedi: %s (%s)", self.path, exc)
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def __enter__(self) -> "RunLock":
        return self.acquire()

    def __exit__(self, *_exc) -> None:
        self.release()
