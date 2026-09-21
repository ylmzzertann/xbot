"""Tur yoneticisi (Runner) testleri: karar -> aksiyon -> kayit akisi."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from xbot.actions import (
    STATUS_BLOCKED,
    STATUS_DRY_RUN,
    STATUS_LIMIT,
    STATUS_WHITELISTED,
    BlockOutcome,
)
from xbot.config import AppConfig
from xbot.errors import SafetyStop
from xbot.models import Level, Tweet
from xbot.runner import Runner
from xbot.scraper import ScrapeResult
from xbot.storage import Storage
from xbot.timefilter import TimeWindow
from xbot.whitelist import Whitelist

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
WINDOW = TimeWindow.last_minutes(60, reference=NOW)


def tweet(tweet_id: str, text: str, username: str | None = None) -> Tweet:
    return Tweet(
        tweet_id=tweet_id,
        username=username or f"user{tweet_id}",
        text=text,
        created_at=NOW - timedelta(minutes=5),
    )


class FakeBlocker:
    """Engellemeyi taklit eder; ne istendigini kaydeder."""

    def __init__(self, *, status: str = STATUS_BLOCKED) -> None:
        self.status = status
        self.calls: list[tuple[str, str]] = []

    def block(self, tw: Tweet, decision, *, mode: str = "auto") -> BlockOutcome:
        self.calls.append((tw.username, mode))
        return BlockOutcome(self.status, tw.username, tw.tweet_id, "mesaj")


class FakeLimiter:
    def __init__(self) -> None:
        self.query_waits = 0

    def wait_between_queries(self) -> float:
        self.query_waits += 1
        return 0.0


@pytest.fixture
def storage(tmp_path):
    with Storage(tmp_path / "runner.sqlite3") as db:
        yield db


@pytest.fixture
def config(project_root):
    return AppConfig.from_dict(
        {
            "search_queries": ["Okan Buruk"],
            "target_names": ["okan", "buruk"],
            "time_window_minutes": 60,
        },
        base_dir=project_root,
    )


def make_runner(
    config,
    engine,
    storage,
    *,
    tweets_by_query: dict[str, list[Tweet]] | None = None,
    blocker=None,
    whitelist=None,
    limiter=None,
    scrape=None,
):
    data = tweets_by_query or {}

    def default_scrape(query: str, window: TimeWindow) -> ScrapeResult:
        items = tuple(data.get(query, ()))
        return ScrapeResult(
            query=query, tweets=items, total_seen=len(items), stop_reason="test"
        )

    return Runner(
        config,
        engine=engine,
        storage=storage,
        whitelist=whitelist if whitelist is not None else Whitelist([]),
        limiter=limiter if limiter is not None else FakeLimiter(),
        blocker=blocker,
        scrape=scrape or default_scrape,
    )


class TestDryRun:
    def test_counts_by_level(self, config, engine, storage):
        tweets = [
            tweet("1", "harika bir maç"),
            tweet("2", "amk gol"),
            tweet("3", "siktir git"),
        ]
        blocker = FakeBlocker(status=STATUS_DRY_RUN)
        runner = make_runner(
            config, engine, storage, tweets_by_query={"Okan Buruk": tweets}, blocker=blocker
        )
        summary = runner.run(auto=False, window=WINDOW)
        assert summary.clean == 1
        assert summary.suspect == 1
        assert summary.high == 1
        assert summary.would_block == 1
        assert summary.blocked == 0
        assert summary.mode == "dry-run"
        assert blocker.calls == [("user3", "dry-run")]

    def test_suspects_are_saved_for_review(self, config, engine, storage):
        runner = make_runner(
            config,
            engine,
            storage,
            tweets_by_query={"Okan Buruk": [tweet("2", "amk gol")]},
            blocker=FakeBlocker(status=STATUS_DRY_RUN),
        )
        runner.run(auto=False, window=WINDOW)
        pending = storage.pending_suspects()
        assert [record.tweet_id for record in pending] == ["2"]

    def test_seen_tweets_are_recorded(self, config, engine, storage):
        runner = make_runner(
            config,
            engine,
            storage,
            tweets_by_query={"Okan Buruk": [tweet("1", "temiz metin")]},
        )
        runner.run(auto=False, window=WINDOW)
        assert storage.is_seen("1") is True

    def test_already_seen_tweets_are_skipped(self, config, engine, storage):
        existing = tweet("1", "siktir git")
        storage.mark_seen(existing, level=Level.HIGH)
        blocker = FakeBlocker()
        runner = make_runner(
            config,
            engine,
            storage,
            tweets_by_query={"Okan Buruk": [existing]},
            blocker=blocker,
        )
        summary = runner.run(auto=True, window=WINDOW)
        assert summary.skipped_seen == 1
        assert summary.high == 0
        assert blocker.calls == []

    def test_whitelisted_user_is_not_evaluated(self, config, engine, storage):
        blocker = FakeBlocker()
        runner = make_runner(
            config,
            engine,
            storage,
            tweets_by_query={"Okan Buruk": [tweet("9", "siktir git", "dostum")]},
            blocker=blocker,
            whitelist=Whitelist(["dostum"]),
        )
        summary = runner.run(auto=True, window=WINDOW)
        assert summary.skipped_whitelist == 1
        assert summary.high == 0
        assert blocker.calls == []


class TestAutoMode:
    def test_high_tweets_are_blocked(self, config, engine, storage):
        blocker = FakeBlocker(status=STATUS_BLOCKED)
        runner = make_runner(
            config,
            engine,
            storage,
            tweets_by_query={"Okan Buruk": [tweet("3", "orospu çocuğu")]},
            blocker=blocker,
        )
        summary = runner.run(auto=True, window=WINDOW)
        assert summary.blocked == 1
        assert blocker.calls == [("user3", "auto")]
        assert summary.mode == "auto"

    def test_limit_moves_tweet_to_suspects(self, config, engine, storage):
        runner = make_runner(
            config,
            engine,
            storage,
            tweets_by_query={"Okan Buruk": [tweet("3", "siktir git")]},
            blocker=FakeBlocker(status=STATUS_LIMIT),
        )
        summary = runner.run(auto=True, window=WINDOW)
        assert summary.limited == 1
        assert summary.blocked == 0
        assert [r.tweet_id for r in storage.pending_suspects()] == ["3"]

    def test_whitelist_outcome_from_blocker_is_counted(self, config, engine, storage):
        runner = make_runner(
            config,
            engine,
            storage,
            tweets_by_query={"Okan Buruk": [tweet("3", "siktir git")]},
            blocker=FakeBlocker(status=STATUS_WHITELISTED),
        )
        summary = runner.run(auto=True, window=WINDOW)
        assert summary.skipped_whitelist == 1


class TestMultipleQueries:
    def test_waits_between_queries(self, config, engine, storage):
        limiter = FakeLimiter()
        runner = make_runner(
            config,
            engine,
            storage,
            tweets_by_query={"a": [tweet("1", "temiz")], "b": [tweet("2", "temiz")]},
            limiter=limiter,
        )
        summary = runner.run(auto=False, queries=["a", "b"], window=WINDOW)
        assert summary.in_window == 2
        assert limiter.query_waits == 1  # son kelimeden sonra beklemez

    def test_same_tweet_in_two_queries_processed_once(self, config, engine, storage):
        shared = tweet("5", "siktir git")
        runner = make_runner(
            config,
            engine,
            storage,
            tweets_by_query={"a": [shared], "b": [shared]},
            blocker=FakeBlocker(status=STATUS_DRY_RUN),
        )
        summary = runner.run(auto=False, queries=["a", "b"], window=WINDOW)
        assert summary.high == 1
        assert summary.skipped_seen == 1


class TestStopping:
    def test_safety_stop_ends_run_and_notifies(self, config, engine, storage):
        messages: list[tuple[str, str]] = []

        def exploding_scrape(query, window):
            raise SafetyStop("CAPTCHA göründü", kind="captcha")

        runner = Runner(
            config,
            engine=engine,
            storage=storage,
            whitelist=Whitelist([]),
            limiter=FakeLimiter(),
            blocker=None,
            scrape=exploding_scrape,
            notifier=lambda title, msg: messages.append((title, msg)),
        )
        summary = runner.run(auto=True, window=WINDOW)
        assert summary.stopped is True
        assert "CAPTCHA" in summary.stop_reason
        assert messages and messages[0][0] == "XBot durdu"
        assert summary.status() == "stopped"

    def test_run_is_recorded_even_when_stopped(self, config, engine, storage):
        def exploding_scrape(query, window):
            raise SafetyStop("durdu")

        runner = Runner(
            config,
            engine=engine,
            storage=storage,
            whitelist=Whitelist([]),
            limiter=FakeLimiter(),
            blocker=None,
            scrape=exploding_scrape,
        )
        runner.run(auto=False, window=WINDOW)
        runs = storage.last_runs()
        assert runs[0]["status"] == "stopped"
        assert runs[0]["finished_at"]

    def test_notifier_failure_is_ignored(self, config, engine, storage):
        def exploding_scrape(query, window):
            raise SafetyStop("durdu")

        def bad_notifier(title, message):
            raise RuntimeError("bildirim yok")

        runner = Runner(
            config,
            engine=engine,
            storage=storage,
            whitelist=Whitelist([]),
            limiter=FakeLimiter(),
            blocker=None,
            scrape=exploding_scrape,
            notifier=bad_notifier,
        )
        summary = runner.run(auto=False, window=WINDOW)
        assert summary.stopped is True


class TestSummaryText:
    def test_lines_are_turkish(self, config, engine, storage):
        runner = make_runner(
            config,
            engine,
            storage,
            tweets_by_query={"Okan Buruk": [tweet("1", "amk gol")]},
        )
        summary = runner.run(auto=False, window=WINDOW)
        text = "\n".join(summary.lines())
        assert "Mod: dry-run" in text
        assert "Şüpheli: 1" in text
        assert "Zaman penceresi: son 60 dakika" in text
