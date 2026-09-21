"""Hiz sinirlari ve beklemeler (guvenlik freni).

Spesifikasyon madde 2: saatlik ve gunluk ust sinir, islemler arasi 8-25 sn ve
kaydirmalar arasi 2-5 sn RASTGELE bekleme. Buradaki hicbir sey "yakalanmamak
icin insan taklidi" degil; amac hem hesabi hem karsi tarafi zorlamamak.

Sayilar veritabanindan okunur: program kapanip acilsa da limit devam eder.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .logging_setup import get_logger


@dataclass(frozen=True, slots=True)
class LimitStatus:
    """Limit durumu."""

    allowed: bool
    reason: str
    used_hour: int
    used_day: int
    limit_hour: int
    limit_day: int

    @property
    def left_hour(self) -> int:
        return max(0, self.limit_hour - self.used_hour)

    @property
    def left_day(self) -> int:
        return max(0, self.limit_day - self.used_day)

    def describe(self) -> str:
        return (
            f"saatlik {self.used_hour}/{self.limit_hour}, "
            f"günlük {self.used_day}/{self.limit_day}"
        )


class RateLimiter:
    """Engelleme sayaclari ve bekleme yoneticisi."""

    def __init__(
        self,
        limits,
        delays,
        *,
        storage=None,
        sleeper=time.sleep,
        rng: random.Random | None = None,
        clock=None,
        logger=None,
    ) -> None:
        self.limits = limits
        self.delays = delays
        self.storage = storage
        self.sleeper = sleeper
        self.rng = rng or random.Random()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.logger = logger or get_logger("limit")
        self._history: list[datetime] = []

    # --- sayaclar ---

    def _counts(self) -> tuple[int, int]:
        now = self.clock()
        if self.storage is not None:
            return (
                self.storage.blocks_last_hour(now=now),
                self.storage.blocks_last_day(now=now),
            )
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)
        return (
            sum(1 for moment in self._history if moment >= hour_ago),
            sum(1 for moment in self._history if moment >= day_ago),
        )

    def status(self) -> LimitStatus:
        """Su anda engelleme yapilabilir mi?"""
        used_hour, used_day = self._counts()
        limit_hour = self.limits.per_hour
        limit_day = self.limits.per_day
        if limit_day <= 0 or limit_hour <= 0:
            return LimitStatus(
                False,
                "Limit 0 olarak ayarlanmış: engelleme kapalı.",
                used_hour,
                used_day,
                limit_hour,
                limit_day,
            )
        if used_day >= limit_day:
            return LimitStatus(
                False,
                f"Günlük engelleme sınırına ulaşıldı ({used_day}/{limit_day}). "
                "Kalan tweetler şüpheli listesine yazılıyor.",
                used_hour,
                used_day,
                limit_hour,
                limit_day,
            )
        if used_hour >= limit_hour:
            return LimitStatus(
                False,
                f"Saatlik engelleme sınırına ulaşıldı ({used_hour}/{limit_hour}). "
                "Kalan tweetler şüpheli listesine yazılıyor.",
                used_hour,
                used_day,
                limit_hour,
                limit_day,
            )
        return LimitStatus(
            True,
            f"Uygun ({used_hour}/{limit_hour} saatlik, {used_day}/{limit_day} günlük)",
            used_hour,
            used_day,
            limit_hour,
            limit_day,
        )

    def allows_block(self) -> bool:
        return self.status().allowed

    def register_block(self) -> None:
        """Yapilan engellemeyi sayaca ekler."""
        self._history.append(self.clock())

    # --- beklemeler ---

    def _sleep_range(self, low: float, high: float, label: str) -> float:
        duration = self.rng.uniform(low, high) if high > low else float(low)
        self.logger.debug("%s için %.1f sn bekleniyor", label, duration)
        if duration > 0:
            self.sleeper(duration)
        return duration

    def wait_between_actions(self) -> float:
        low, high = self.delays.between_actions
        return self._sleep_range(low, high, "işlemler arası")

    def wait_between_scrolls(self) -> float:
        low, high = self.delays.between_scrolls
        return self._sleep_range(low, high, "kaydırmalar arası")

    def wait_between_queries(self) -> float:
        """Iki arama kelimesi arasinda islem beklemesi kadar bekler."""
        return self.wait_between_actions()
