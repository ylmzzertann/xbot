"""Zaman filtresi testleri."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from xbot.models import Tweet
from xbot.timefilter import TimeWindow, filter_recent, parse_tweet_time

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def tweet_at(minutes_ago: float | None, tweet_id: str = "1") -> Tweet:
    created = None if minutes_ago is None else NOW - timedelta(minutes=minutes_ago)
    return Tweet(tweet_id=tweet_id, username="user", text="metin", created_at=created)


class TestParseTweetTime:
    def test_z_suffix(self):
        moment = parse_tweet_time("2026-09-20T12:34:56.000Z")
        assert moment == datetime(2026, 9, 20, 12, 34, 56, tzinfo=timezone.utc)

    def test_offset_form(self):
        moment = parse_tweet_time("2026-09-20T15:34:56+03:00")
        assert moment == datetime(2026, 9, 20, 12, 34, 56, tzinfo=timezone.utc)

    def test_naive_is_assumed_utc(self):
        assert parse_tweet_time("2026-09-20T12:00:00").tzinfo is timezone.utc

    @pytest.mark.parametrize("value", [None, "", "   ", "dün", "20.09.2026"])
    def test_invalid_values_return_none(self, value):
        assert parse_tweet_time(value) is None


class TestTimeWindow:
    def test_start_is_n_minutes_back(self):
        window = TimeWindow.last_minutes(60, reference=NOW)
        assert window.start == NOW - timedelta(minutes=60)

    def test_contains(self):
        window = TimeWindow.last_minutes(60, reference=NOW)
        assert window.contains(NOW - timedelta(minutes=30)) is True
        assert window.contains(NOW - timedelta(minutes=90)) is False
        assert window.contains(None) is False

    def test_small_future_tolerance(self):
        """Saat farki yuzunden 1 dakika ileri tarihli tweet atilmasin."""
        window = TimeWindow.last_minutes(60, reference=NOW)
        assert window.contains(NOW + timedelta(minutes=1)) is True
        assert window.contains(NOW + timedelta(minutes=10)) is False

    def test_is_older(self):
        window = TimeWindow.last_minutes(60, reference=NOW)
        assert window.is_older(NOW - timedelta(minutes=61)) is True
        assert window.is_older(NOW - timedelta(minutes=10)) is False
        assert window.is_older(None) is False

    def test_zero_minutes_rejected(self):
        with pytest.raises(ValueError, match="en az 1 dakika"):
            TimeWindow.last_minutes(0)

    def test_describe_is_turkish(self):
        assert "son 60 dakika" in TimeWindow.last_minutes(60, reference=NOW).describe()


class TestFilterRecent:
    def test_keeps_only_recent(self):
        window = TimeWindow.last_minutes(60, reference=NOW)
        tweets = [tweet_at(5, "a"), tweet_at(120, "b"), tweet_at(59, "c")]
        result = filter_recent(tweets, window)
        assert [t.tweet_id for t in result.kept] == ["a", "c"]
        assert result.too_old == 1
        assert result.dropped == 1

    def test_unknown_time_is_dropped_by_default(self):
        window = TimeWindow.last_minutes(60, reference=NOW)
        result = filter_recent([tweet_at(None, "x")], window)
        assert result.kept == ()
        assert result.unknown_time == 1

    def test_unknown_time_can_be_included(self):
        window = TimeWindow.last_minutes(60, reference=NOW)
        result = filter_recent([tweet_at(None, "x")], window, include_unknown=True)
        assert [t.tweet_id for t in result.kept] == ["x"]

    def test_empty_input(self):
        window = TimeWindow.last_minutes(60, reference=NOW)
        result = filter_recent([], window)
        assert result.kept == ()
        assert result.dropped == 0
