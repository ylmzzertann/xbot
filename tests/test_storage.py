"""SQLite kayit katmani testleri."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from xbot.models import Decision, Level, Match, Severity, Tweet
from xbot.storage import (
    SUSPECT_BLOCKED,
    SUSPECT_DISMISSED,
    SUSPECT_PENDING,
    Storage,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    with Storage(tmp_path / "test.sqlite3") as storage:
        yield storage


def make_tweet(tweet_id="1", username="kotu_hesap", text="siktir git") -> Tweet:
    return Tweet(tweet_id=tweet_id, username=username, text=text, created_at=NOW)


def make_decision(tweet: Tweet, level: Level = Level.HIGH) -> Decision:
    return Decision(
        tweet=tweet,
        level=level,
        matches=(Match("profanity", "siktir", Severity.STRONG, "siktir"),),
        reasons=("güçlü eşleşme", "Açık küfür → YÜKSEK."),
    )


class TestSchema:
    def test_database_file_is_created(self, tmp_path):
        path = tmp_path / "alt" / "veri.sqlite3"
        with Storage(path):
            pass
        assert path.exists()

    def test_reopen_keeps_data(self, tmp_path):
        path = tmp_path / "veri.sqlite3"
        tweet = make_tweet()
        with Storage(path) as storage:
            storage.mark_seen(tweet, level=Level.HIGH)
        with Storage(path) as storage:
            assert storage.is_seen("1") is True


class TestSeenTweets:
    def test_mark_and_check(self, db):
        tweet = make_tweet()
        assert db.is_seen("1") is False
        db.mark_seen(tweet, level=Level.HIGH, rules="siktir", query="Okan Buruk")
        assert db.is_seen("1") is True
        assert db.seen_count() == 1

    def test_marking_twice_does_not_duplicate(self, db):
        tweet = make_tweet()
        db.mark_seen(tweet, level=Level.SUSPECT)
        db.mark_seen(tweet, level=Level.HIGH)
        assert db.seen_count() == 1


class TestBlocks:
    def test_record_and_query(self, db):
        tweet = make_tweet()
        record_id = db.record_block(tweet, make_decision(tweet))
        assert record_id > 0
        assert db.is_blocked("kotu_hesap") is True
        assert db.is_blocked("@KOTU_HESAP") is True  # buyuk/kucuk ve @ farki yok
        assert db.is_blocked("baska") is False

    def test_evidence_is_stored(self, db):
        tweet = make_tweet(text="orospu çocuğu")
        db.record_block(tweet, make_decision(tweet))
        record = db.recent_blocks(1)[0]
        assert record.username == "kotu_hesap"
        assert record.text == "orospu çocuğu"
        assert record.url == "https://x.com/kotu_hesap/status/1"
        assert record.rules == "siktir"
        assert "Açık küfür" in record.reasons
        assert record.level == "HIGH"
        assert "Engeli kaldırmak" in record.undo_hint() or "engel" in record.undo_hint()

    def test_counts_by_time(self, db):
        tweet = make_tweet()
        db.record_block(tweet, make_decision(tweet))
        assert db.blocks_last_hour() == 1
        assert db.blocks_last_day() == 1
        future = datetime.now(timezone.utc) + timedelta(days=2)
        assert db.blocks_last_hour(now=future) == 0

    def test_undone_blocks_are_not_counted(self, db):
        tweet = make_tweet()
        record_id = db.record_block(tweet, make_decision(tweet))
        assert db.mark_block_undone(record_id, note="yanlış engelleme") is True
        assert db.is_blocked("kotu_hesap") is False
        assert db.blocks_last_hour() == 0
        assert db.recent_blocks(5)[0].undone is True

    def test_mark_unknown_block(self, db):
        assert db.mark_block_undone(999) is False

    def test_recent_blocks_can_hide_undone(self, db):
        tweet = make_tweet()
        record_id = db.record_block(tweet, make_decision(tweet))
        db.mark_block_undone(record_id)
        assert db.recent_blocks(5, include_undone=False) == []


class TestSuspects:
    def test_add_and_list(self, db):
        tweet = make_tweet(text="amk gol")
        db.add_suspect(tweet, make_decision(tweet, Level.SUSPECT))
        pending = db.pending_suspects()
        assert len(pending) == 1
        assert pending[0].status == SUSPECT_PENDING
        assert pending[0].text == "amk gol"

    def test_status_change(self, db):
        tweet = make_tweet()
        db.add_suspect(tweet, make_decision(tweet, Level.SUSPECT))
        assert db.set_suspect_status("1", SUSPECT_BLOCKED) is True
        assert db.pending_suspects() == []
        assert db.all_suspects()[0].status == SUSPECT_BLOCKED

    def test_invalid_status(self, db):
        with pytest.raises(ValueError, match="Geçersiz şüpheli durumu"):
            db.set_suspect_status("1", "belki")

    def test_suspect_to_tweet(self, db):
        tweet = make_tweet(text="amk")
        db.add_suspect(tweet, make_decision(tweet, Level.SUSPECT))
        again = db.pending_suspects()[0].as_tweet()
        assert again.username == "kotu_hesap"
        assert again.created_at == NOW
        assert again.permalink == tweet.permalink

    def test_adding_same_suspect_twice(self, db):
        tweet = make_tweet()
        db.add_suspect(tweet, make_decision(tweet, Level.SUSPECT))
        db.add_suspect(tweet, make_decision(tweet, Level.SUSPECT))
        assert len(db.pending_suspects()) == 1


class TestRuns:
    def test_start_and_finish(self, db):
        run_id = db.start_run(mode="dry-run", queries=["Okan Buruk", "Galatasaray"])
        db.finish_run(run_id, seen=10, high=2, suspect=3, blocked=0, status="ok")
        runs = db.last_runs()
        assert runs[0]["mode"] == "dry-run"
        assert runs[0]["seen"] == 10
        assert runs[0]["status"] == "ok"
        assert "Galatasaray" in runs[0]["queries"]


class TestStats:
    def test_empty_database(self, db):
        stats = db.stats()
        assert stats["gorulen_tweet"] == 0
        assert stats["engellenen"] == 0
        assert stats["son_calisma"] == "(hiç çalışmadı)"

    def test_filled_database(self, db):
        tweet = make_tweet()
        db.mark_seen(tweet, level=Level.HIGH)
        db.record_block(tweet, make_decision(tweet))
        db.add_suspect(make_tweet("2"), make_decision(make_tweet("2"), Level.SUSPECT))
        db.set_suspect_status("2", SUSPECT_DISMISSED)
        run_id = db.start_run(mode="auto", queries=["x"])
        db.finish_run(run_id)
        stats = db.stats()
        assert stats["gorulen_tweet"] == 1
        assert stats["engellenen"] == 1
        assert stats["supheli_temizlenen"] == 1
        assert stats["calisma_sayisi"] == 1
        assert "auto" in stats["son_calisma"]
