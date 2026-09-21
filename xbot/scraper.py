"""Arama sayfasini tarar ve tweetleri toplar.

Akis:
  1. https://x.com/search?q=...&f=live  ("Son" sekmesi) acilir
  2. Gorunen tweetler okunur (kullanici adi, metin, tweet id, <time datetime>)
  3. Kontrollu kaydirma yapilir (aralar rastgele bekleme ile)
  4. Zaman penceresinden (varsayilan son 60 dakika) eski tweetler gorulmeye
     baslayinca kaydirma durur

DOM erisimi TweetSource arayuzunun arkasinda: boylece kaydirma/durma mantigi
tarayici olmadan test edilebilir.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from . import selectors
from .browser import find_first, require_first
from .errors import SelectorNotFound
from .logging_setup import get_logger
from .models import Tweet
from .timefilter import TimeWindow, filter_recent, parse_tweet_time

#: /kullanici/status/1234567890 -> ("kullanici", "1234567890")
PERMALINK_RE = re.compile(r"^/([A-Za-z0-9_]{1,20})/status/(\d+)")

#: X'in kendi ic yollari: kullanici adi degil
RESERVED_HANDLES = frozenset(
    {"i", "home", "explore", "search", "notifications", "messages", "settings", "compose"}
)

#: Kaydirma sirasinda kac kez yeni tweet gelmezse durulur
EMPTY_SCROLL_LIMIT = 2

#: Ust uste kac eski tweet gorulurse pencere bitti sayilir
OLD_TWEET_STREAK = 3


@dataclass(frozen=True, slots=True)
class RawTweet:
    """DOM'dan okunmus ham tweet."""

    tweet_id: str
    username: str
    text: str
    timestamp: str = ""
    url: str = ""
    display_name: str = ""


def parse_permalink(href: str | None) -> tuple[str, str] | None:
    """Kalici baglantidan (kullanici adi, tweet id) cikarir."""
    if not href:
        return None
    path = href.split("?", 1)[0]
    if path.startswith("http"):
        cut = path.find("/", path.find("//") + 2)
        path = path[cut:] if cut > 0 else path
    match = PERMALINK_RE.match(path)
    if not match:
        return None
    username = match.group(1)
    if username.lower() in RESERVED_HANDLES:
        return None
    return username, match.group(2)


def build_tweet(raw: RawTweet) -> Tweet | None:
    """Ham tweeti dogrulanmis Tweet nesnesine cevirir (metinsizleri atar)."""
    if not raw.tweet_id or not raw.username:
        return None
    text = (raw.text or "").strip()
    if not text:
        return None
    return Tweet(
        tweet_id=raw.tweet_id,
        username=raw.username,
        text=text,
        created_at=parse_tweet_time(raw.timestamp),
        url=raw.url or selectors.status_url(raw.username, raw.tweet_id),
        display_name=raw.display_name or "",
    )


class TweetSource(Protocol):
    """Scraper'in DOM'dan bekledigi en kucuk arayuz."""

    def visible_tweets(self) -> list[RawTweet]:
        """O an ekranda/DOM'da bulunan tweetler."""

    def scroll_once(self) -> None:
        """Bir kez asagi kaydirir ve kisa bir sure bekler."""

    def has_results(self) -> bool:
        """Sayfada hic sonuc var mi? (yoksa bos sonuc sayfasidir)"""


# --------------------------------------------------------------------------
# gercek (Playwright) kaynak
# --------------------------------------------------------------------------


class PlaywrightTweetSource:
    """Playwright sayfasindan tweet okur."""

    def __init__(self, page, *, session=None, delays=None, logger=None) -> None:
        self.page = page
        self.session = session
        self.delays = delays  # RateLimiter benzeri: wait_between_scrolls()
        self.logger = logger or get_logger("scraper")

    # --- okuma ---

    def has_results(self) -> bool:
        if find_first(self.page, (selectors.EMPTY_STATE,)) is not None:
            return False
        return find_first(self.page, selectors.CHAINS["tweet"]) is not None

    def visible_tweets(self) -> list[RawTweet]:
        """Gorunen tweet kutularini okur."""
        found = find_first(self.page, selectors.CHAINS["tweet"])
        if found is None:
            if not self.has_results():
                return []
            require_first(
                self.page,
                selectors.CHAINS["tweet"],
                what="tweet kutusu",
                session=self.session,
                logger=self.logger,
            )
        selector = found[0] if found else selectors.TWEET
        articles = self.page.locator(selector)
        total = articles.count()
        out: list[RawTweet] = []
        for index in range(total):
            try:
                raw = self._read_article(articles.nth(index))
            except SelectorNotFound:
                raise
            except Exception as exc:  # pragma: no cover - tek tweet okunamadi
                self.logger.debug("Bir tweet okunamadı (atlandı): %s", exc)
                continue
            if raw is not None:
                out.append(raw)
        return out

    def _read_article(self, article) -> RawTweet | None:
        """Tek bir tweet kutusunu okur."""
        link = find_first(article, selectors.CHAINS["permalink"])
        if link is None:
            # Reklam/oneri kutulari kalici baglanti icermez: sessizce atla
            return None
        href = link[1].get_attribute("href")
        parsed = parse_permalink(href)
        if parsed is None:
            return None
        username, tweet_id = parsed

        timestamp = ""
        try:
            time_element = link[1].locator(selectors.TIME).first
            if time_element.count() > 0:
                timestamp = time_element.get_attribute("datetime") or ""
        except Exception:  # pragma: no cover
            timestamp = ""

        text = ""
        text_found = find_first(article, selectors.CHAINS["tweet_text"])
        if text_found is not None:
            try:
                parts = article.locator(text_found[0])
                text = "\n".join(
                    parts.nth(i).inner_text() for i in range(min(parts.count(), 3))
                )
            except Exception:  # pragma: no cover
                text = ""

        display_name = ""
        name_found = find_first(article, (selectors.USER_NAME,))
        if name_found is not None:
            try:
                display_name = (name_found[1].inner_text() or "").split("\n")[0]
            except Exception:  # pragma: no cover
                display_name = ""

        return RawTweet(
            tweet_id=tweet_id,
            username=username,
            text=text,
            timestamp=timestamp,
            url=selectors.status_url(username, tweet_id),
            display_name=display_name,
        )

    # --- kaydirma ---

    def scroll_once(self) -> None:
        try:
            self.page.mouse.wheel(0, 1600)
        except Exception:  # pragma: no cover - fare yoksa klavye ile
            self.page.keyboard.press("PageDown")
        if self.delays is not None:
            self.delays.wait_between_scrolls()


# --------------------------------------------------------------------------
# tarama mantigi (tarayicidan bagimsiz)
# --------------------------------------------------------------------------


@dataclass
class ScrapeResult:
    """Tek bir arama kelimesinin tarama sonucu."""

    query: str
    tweets: tuple[Tweet, ...] = ()
    total_seen: int = 0
    too_old: int = 0
    unknown_time: int = 0
    skipped_textless: int = 0
    scrolls: int = 0
    stop_reason: str = ""
    empty_page: bool = False

    @property
    def count(self) -> int:
        return len(self.tweets)

    def describe(self) -> str:
        return (
            f"'{self.query}': {self.count} tweet pencere içinde "
            f"({self.total_seen} görüldü, {self.too_old} eski, "
            f"{self.unknown_time} tarihsiz, {self.scrolls} kaydırma) — "
            f"durma nedeni: {self.stop_reason}"
        )


class SearchScraper:
    """Bir arama kelimesi icin kontrollu tarama yapar."""

    def __init__(
        self,
        source: TweetSource,
        *,
        max_scrolls: int = 15,
        logger=None,
    ) -> None:
        self.source = source
        self.max_scrolls = max_scrolls
        self.logger = logger or get_logger("scraper")

    def scrape(self, query: str, window: TimeWindow) -> ScrapeResult:
        """Tweetleri toplar; pencere bitince veya sinirlar dolunca durur."""
        collected: dict[str, Tweet] = {}
        seen_ids: set[str] = set()
        textless = 0
        old_streak = 0
        empty_scrolls = 0
        scrolls = 0
        stop_reason = "kaydırma sınırına ulaşıldı"

        if not self.source.has_results():
            return ScrapeResult(
                query=query,
                stop_reason="sonuç bulunamadı",
                empty_page=True,
            )

        while True:
            new_in_round = 0
            for raw in self.source.visible_tweets():
                if raw.tweet_id in seen_ids:
                    continue
                seen_ids.add(raw.tweet_id)
                new_in_round += 1
                tweet = build_tweet(raw)
                if tweet is None:
                    textless += 1
                    continue
                collected[tweet.tweet_id] = tweet
                if window.is_older(tweet.created_at):
                    old_streak += 1
                else:
                    old_streak = 0

            if old_streak >= OLD_TWEET_STREAK:
                stop_reason = "zaman penceresinin sonuna gelindi"
                break
            if new_in_round == 0:
                empty_scrolls += 1
                if empty_scrolls >= EMPTY_SCROLL_LIMIT:
                    stop_reason = "yeni tweet gelmedi"
                    break
            else:
                empty_scrolls = 0
            if scrolls >= self.max_scrolls:
                stop_reason = "kaydırma sınırına ulaşıldı"
                break

            self.source.scroll_once()
            scrolls += 1

        filtered = filter_recent(collected.values(), window)
        result = ScrapeResult(
            query=query,
            tweets=filtered.kept,
            total_seen=len(seen_ids),
            too_old=filtered.too_old,
            unknown_time=filtered.unknown_time,
            skipped_textless=textless,
            scrolls=scrolls,
            stop_reason=stop_reason,
        )
        self.logger.info(result.describe())
        return result
