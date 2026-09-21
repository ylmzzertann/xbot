"""Tarama testleri: DOM okuma (sahte sayfa) ve kaydirma/durma mantigi."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from xbot import selectors
from xbot.scraper import (
    EMPTY_SCROLL_LIMIT,
    PlaywrightTweetSource,
    RawTweet,
    SearchScraper,
    build_tweet,
    parse_permalink,
)
from xbot.timefilter import TimeWindow

from fakes import FakeNode, FakePage, make_search_page, make_tweet_node

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
WINDOW = TimeWindow.last_minutes(60, reference=NOW)


def stamp(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def raw(tweet_id: str, minutes_ago: float = 5, text: str = "metin") -> RawTweet:
    return RawTweet(
        tweet_id=tweet_id,
        username=f"user{tweet_id}",
        text=text,
        timestamp=stamp(minutes_ago),
    )


class TestParsePermalink:
    @pytest.mark.parametrize(
        "href,expected",
        [
            ("/okanburuk/status/1234567890", ("okanburuk", "1234567890")),
            ("https://x.com/abc/status/999/photo/1", ("abc", "999")),
            ("/abc/status/999?s=20", ("abc", "999")),
            ("/Ab_c9/status/1", ("Ab_c9", "1")),
        ],
    )
    def test_valid(self, href, expected):
        assert parse_permalink(href) == expected

    @pytest.mark.parametrize(
        "href",
        [None, "", "/okan/statu/12", "/status/12", "/i/status/12", "/home", "/explore/tabs"],
    )
    def test_invalid(self, href):
        assert parse_permalink(href) is None


class TestBuildTweet:
    def test_full_tweet(self):
        tweet = build_tweet(raw("55", 10, "siktir git"))
        assert tweet is not None
        assert tweet.tweet_id == "55"
        assert tweet.username == "user55"
        assert tweet.created_at == NOW - timedelta(minutes=10)
        assert tweet.permalink == "https://x.com/user55/status/55"

    def test_textless_tweet_is_dropped(self):
        assert build_tweet(RawTweet("1", "user", "   ")) is None

    def test_missing_id_or_user(self):
        assert build_tweet(RawTweet("", "user", "metin")) is None
        assert build_tweet(RawTweet("1", "", "metin")) is None

    def test_unknown_time_is_allowed_here(self):
        """Tarih cozumlenemezse Tweet uretilir; filtre asamasinda atilir."""
        tweet = build_tweet(RawTweet("1", "user", "metin", timestamp="dun"))
        assert tweet is not None and tweet.created_at is None


class TestPlaywrightTweetSource:
    def test_reads_fields_from_dom(self):
        page = make_search_page(
            [
                make_tweet_node(
                    username="kotu", tweet_id="111", text="siktir git", timestamp=stamp(5)
                ),
                make_tweet_node(
                    username="iyi", tweet_id="222", text="harika maç", timestamp=stamp(9)
                ),
            ]
        )
        tweets = PlaywrightTweetSource(page).visible_tweets()
        assert [t.tweet_id for t in tweets] == ["111", "222"]
        assert tweets[0].username == "kotu"
        assert tweets[0].text == "siktir git"
        assert tweets[0].timestamp == stamp(5)
        assert tweets[0].display_name == "Kötü Hesap"
        assert tweets[0].url == "https://x.com/kotu/status/111"

    def test_node_without_permalink_is_skipped(self):
        page = make_search_page([FakeNode(), make_tweet_node(tweet_id="7")])
        tweets = PlaywrightTweetSource(page).visible_tweets()
        assert [t.tweet_id for t in tweets] == ["7"]

    def test_has_results_true_when_tweets_exist(self):
        page = make_search_page([make_tweet_node()])
        assert PlaywrightTweetSource(page).has_results() is True

    def test_empty_state_means_no_results(self):
        page = FakePage(nodes={selectors.EMPTY_STATE: [FakeNode(text="Sonuç yok")]})
        source = PlaywrightTweetSource(page)
        assert source.has_results() is False
        assert source.visible_tweets() == []

    def test_scroll_uses_mouse_and_waits(self):
        page = make_search_page([make_tweet_node()])

        class Delays:
            def __init__(self):
                self.calls = 0

            def wait_between_scrolls(self):
                self.calls += 1

        delays = Delays()
        PlaywrightTweetSource(page, delays=delays).scroll_once()
        assert page.mouse.wheels == 1
        assert delays.calls == 1


class FakeSource:
    """Kaydirdikca yeni tweet gosteren sahte kaynak."""

    def __init__(self, pages: list[list[RawTweet]], *, has_results: bool = True) -> None:
        self.pages = pages
        self.index = 0
        self.scrolls = 0
        self._has_results = has_results

    def has_results(self) -> bool:
        return self._has_results

    def visible_tweets(self) -> list[RawTweet]:
        return self.pages[min(self.index, len(self.pages) - 1)]

    def scroll_once(self) -> None:
        self.index += 1
        self.scrolls += 1


class TestSearchScraper:
    def test_collects_across_scrolls(self):
        pages = [
            [raw("1"), raw("2")],
            [raw("1"), raw("2"), raw("3")],
            [raw("1"), raw("2"), raw("3"), raw("4")],
        ]
        source = FakeSource(pages)
        result = SearchScraper(source, max_scrolls=5).scrape("Okan Buruk", WINDOW)
        assert {t.tweet_id for t in result.tweets} == {"1", "2", "3", "4"}
        assert result.total_seen == 4
        assert result.query == "Okan Buruk"

    def test_stops_when_no_new_tweets(self):
        source = FakeSource([[raw("1")]])
        result = SearchScraper(source, max_scrolls=50).scrape("x", WINDOW)
        assert result.stop_reason == "yeni tweet gelmedi"
        assert source.scrolls == EMPTY_SCROLL_LIMIT

    def test_stops_at_window_end(self):
        pages = [
            [raw("1", 5)],
            [raw("1", 5), raw("2", 90), raw("3", 95), raw("4", 100)],
        ]
        source = FakeSource(pages)
        result = SearchScraper(source, max_scrolls=50).scrape("x", WINDOW)
        assert result.stop_reason == "zaman penceresinin sonuna gelindi"
        assert [t.tweet_id for t in result.tweets] == ["1"]
        assert result.too_old == 3

    def test_respects_max_scrolls(self):
        pages = [[raw(str(i)) for i in range(n + 1)] for n in range(10)]
        source = FakeSource(pages)
        result = SearchScraper(source, max_scrolls=2).scrape("x", WINDOW)
        assert source.scrolls == 2
        assert result.stop_reason == "kaydırma sınırına ulaşıldı"

    def test_zero_scrolls_reads_first_screen_only(self):
        source = FakeSource([[raw("1"), raw("2")], [raw("3")]])
        result = SearchScraper(source, max_scrolls=0).scrape("x", WINDOW)
        assert source.scrolls == 0
        assert len(result.tweets) == 2

    def test_empty_page(self):
        source = FakeSource([[]], has_results=False)
        result = SearchScraper(source).scrape("bulunamaz", WINDOW)
        assert result.empty_page is True
        assert result.count == 0
        assert result.stop_reason == "sonuç bulunamadı"

    def test_textless_tweets_counted_separately(self):
        source = FakeSource([[RawTweet("1", "user", "", stamp(5)), raw("2")]])
        result = SearchScraper(source).scrape("x", WINDOW)
        assert result.skipped_textless == 1
        assert [t.tweet_id for t in result.tweets] == ["2"]

    def test_unknown_time_is_reported(self):
        source = FakeSource([[RawTweet("1", "user", "metin", "")]])
        result = SearchScraper(source).scrape("x", WINDOW)
        assert result.unknown_time == 1
        assert result.tweets == ()

    def test_describe_is_turkish(self):
        source = FakeSource([[raw("1")]])
        result = SearchScraper(source).scrape("Okan Buruk", WINDOW)
        assert "tweet pencere içinde" in result.describe()
