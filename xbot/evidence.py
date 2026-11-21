"""Engellenen hesaplarin yazdiklarini biriktiren dosya.

Her basarili engellemede, o hesabin taramada bulunan tweet(ler)i tek bir CSV
dosyasina EKLENIR (eski kayitlar silinmez). Dosya Excel'de dogrudan acilir:
UTF-8 BOM + noktali virgul ayirici.

Varsayilan yol: kayitlar/engellenen_tweetler.csv
(config.yaml -> paths.blocked_tweets ile degistirilebilir)

Dosyada baskalarinin yazdiklari oldugu icin .gitignore icindedir; paylasma.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from .models import Tweet

HEADERS = (
    "kayit_zamani",
    "hesap",
    "gorunen_ad",
    "tweet_id",
    "tweet_metni",
    "tweet_linki",
    "tweet_zamani",
    "sebep",
    "mod",
)


def _local(moment: datetime | None) -> str:
    """Tarihi yerel saatle okunakli yazar: 21.09.2026 14:05"""
    if moment is None:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%d.%m.%Y %H:%M")


class BlockedTweetLog:
    """Engellenenlerin tweetlerini CSV dosyasina ekler."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(
        self,
        tweets: Sequence[Tweet],
        *,
        reason: str = "",
        mode: str = "",
        recorded_at: datetime | None = None,
    ) -> int:
        """Tweetleri dosyanin sonuna ekler; eklenen satir sayisini dondurur."""
        if not tweets:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.path.exists() or self.path.stat().st_size == 0
        # BOM sadece dosyanin basina yazilir; sonradan eklerken yazilmaz
        encoding = "utf-8-sig" if is_new else "utf-8"
        stamp = (recorded_at or datetime.now(timezone.utc)).astimezone().strftime(
            "%d.%m.%Y %H:%M:%S"
        )
        with self.path.open("a", encoding=encoding, newline="") as handle:
            writer = csv.writer(handle, delimiter=";", quoting=csv.QUOTE_MINIMAL)
            if is_new:
                writer.writerow(HEADERS)
            for tweet in tweets:
                writer.writerow(
                    (
                        stamp,
                        tweet.username,
                        tweet.display_name,
                        tweet.tweet_id,
                        tweet.text,
                        tweet.permalink,
                        _local(tweet.created_at),
                        reason,
                        mode,
                    )
                )
        return len(tweets)

    def read(self) -> list[dict[str, str]]:
        """Dosyadaki tum kayitlari okur (yoksa bos liste)."""
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle, delimiter=";"))

    def count(self) -> int:
        return len(self.read())
