"""Zaman penceresi: sadece son N dakikadaki tweetleri gecirir.

X arayuzunde her tweetin tarihi <time datetime="2026-09-20T12:34:56.000Z">
seklinde durur. Bu modul o degeri cozer ve pencere disindakileri atar.

Varsayim: tarihi okunamayan tweet pencere DISINDA sayilir (sessizce islenmez).
Boylece "eski tweeti yanlislikla engelleme" riski olusmaz.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import Tweet


def parse_tweet_time(value: str | None) -> datetime | None:
    """ISO 8601 tarih metnini (UTC) datetime'a cevirir."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """[simdi - N dakika, simdi] araligi."""

    minutes: int
    reference: datetime

    @classmethod
    def last_minutes(cls, minutes: int, *, reference: datetime | None = None) -> "TimeWindow":
        if minutes <= 0:
            raise ValueError("Zaman penceresi en az 1 dakika olmalı.")
        return cls(minutes=minutes, reference=reference or now_utc())

    @property
    def start(self) -> datetime:
        return self.reference - timedelta(minutes=self.minutes)

    @property
    def end(self) -> datetime:
        # Saat farki/gecikme yuzunden birkac dakika ileri tarihli tweetler olabilir
        return self.reference + timedelta(minutes=2)

    def contains(self, moment: datetime | None) -> bool:
        """Tarih pencerede mi? Tarih yoksa hayir."""
        if moment is None:
            return False
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        moment = moment.astimezone(timezone.utc)
        return self.start <= moment <= self.end

    def is_older(self, moment: datetime | None) -> bool:
        """Tweet pencereden daha eski mi? (kaydirmayi durdurmak icin)"""
        if moment is None:
            return False
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc) < self.start

    def describe(self) -> str:
        return (
            f"son {self.minutes} dakika "
            f"({self.start:%d.%m.%Y %H:%M} - {self.reference:%H:%M} UTC)"
        )


@dataclass(frozen=True, slots=True)
class FilterResult:
    """Filtreleme sonucu (raporlanabilir sayaclarla)."""

    kept: tuple[Tweet, ...]
    too_old: int = 0
    unknown_time: int = 0

    @property
    def dropped(self) -> int:
        return self.too_old + self.unknown_time


def filter_recent(
    tweets: Iterable[Tweet] | Sequence[Tweet],
    window: TimeWindow,
    *,
    include_unknown: bool = False,
) -> FilterResult:
    """Pencere disindaki tweetleri ayiklar."""
    kept: list[Tweet] = []
    too_old = 0
    unknown = 0
    for tweet in tweets:
        if tweet.created_at is None:
            if include_unknown:
                kept.append(tweet)
            else:
                unknown += 1
            continue
        if window.contains(tweet.created_at):
            kept.append(tweet)
        else:
            too_old += 1
    return FilterResult(kept=tuple(kept), too_old=too_old, unknown_time=unknown)
