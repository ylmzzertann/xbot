"""Rapor (CSV + HTML) testleri."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from xbot.models import Decision, Level, Match, Severity, Tweet
from xbot.report import (
    BLOCK_HEADERS,
    ReportBuilder,
    block_row,
    render_html,
    suspect_row,
    write_csv,
)
from xbot.storage import Storage

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def make_tweet(tweet_id="1", username="kotu_hesap", text="siktir git") -> Tweet:
    return Tweet(tweet_id=tweet_id, username=username, text=text, created_at=NOW)


def make_decision(tweet: Tweet, level: Level = Level.HIGH) -> Decision:
    return Decision(
        tweet=tweet,
        level=level,
        matches=(Match("profanity", "siktir", Severity.STRONG, "siktir"),),
        reasons=("güçlü eşleşme 'siktir'",),
    )


@pytest.fixture
def filled_db(tmp_path):
    with Storage(tmp_path / "rapor.sqlite3") as db:
        blocked = make_tweet("1", "kotu_hesap", "siktir git okan")
        db.record_block(blocked, make_decision(blocked))
        suspect = make_tweet("2", "belirsiz_hesap", "amk gol")
        db.add_suspect(suspect, make_decision(suspect, Level.SUSPECT))
        yield db


class TestCsv:
    def test_write_csv_is_excel_friendly(self, tmp_path):
        path = write_csv(tmp_path / "test.csv", ("a", "b"), [("1", "2")])
        raw = path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
        text = raw.decode("utf-8-sig")
        assert text.splitlines()[0] == "a;b"

    def test_block_row_has_all_evidence(self, filled_db):
        record = filled_db.recent_blocks(1)[0]
        row = block_row(record)
        assert len(row) == len(BLOCK_HEADERS)
        assert row[0] == "kotu_hesap"
        assert "siktir git okan" in row[2]
        assert row[3] == "https://x.com/kotu_hesap/status/1"
        assert row[5] == "siktir"
        assert row[10] == "hayır"  # geri alinmadi

    def test_newlines_are_flattened(self, filled_db):
        tweet = make_tweet("3", text="birinci satır\nikinci satır")
        filled_db.record_block(tweet, make_decision(tweet))
        row = block_row(filled_db.recent_blocks(1)[0])
        assert "\n" not in row[2]

    def test_suspect_row(self, filled_db):
        record = filled_db.all_suspects()[0]
        row = suspect_row(record)
        assert row[0] == "belirsiz_hesap"
        assert row[7] == "pending"


class TestHtml:
    def test_contains_tables_and_counts(self, filled_db):
        html = render_html(
            blocks=filled_db.recent_blocks(10),
            suspects=filled_db.all_suspects(10),
            stats=filled_db.stats(),
            summary_lines=["Mod: dry-run", "Görülen tweet: 5"],
        )
        assert "<!DOCTYPE html>" in html
        assert "Engellenen hesaplar (1)" in html
        assert "Şüpheli tweetler (1)" in html
        assert "@kotu_hesap" in html
        assert "Mod: dry-run" in html
        assert 'lang="tr"' in html

    def test_html_is_escaped(self, filled_db):
        tweet = make_tweet("9", "hacker", "<script>alert(1)</script> siktir")
        filled_db.record_block(tweet, make_decision(tweet))
        html = render_html(blocks=filled_db.recent_blocks(10), suspects=[])
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_empty_report(self, tmp_path):
        html = render_html(blocks=[], suspects=[])
        assert "Kayıt yok." in html

    def test_undone_block_is_marked(self, filled_db):
        record_id = filled_db.recent_blocks(1)[0].id
        filled_db.mark_block_undone(record_id)
        html = render_html(blocks=filled_db.recent_blocks(10), suspects=[])
        assert "geri alındı" in html


class TestReportBuilder:
    def test_build_creates_all_files(self, filled_db, tmp_path):
        paths = ReportBuilder(filled_db, tmp_path / "rapor").build(stamp="deneme")
        assert paths.html.name == "rapor-deneme.html"
        assert paths.blocks_csv.name == "engellenenler-deneme.csv"
        assert paths.suspects_csv.name == "supheliler-deneme.csv"
        assert len(paths.existing()) == 3
        for path in paths.existing():
            assert path.exists()

    def test_latest_report_alias_is_written(self, filled_db, tmp_path):
        directory = tmp_path / "rapor"
        ReportBuilder(filled_db, directory).build(stamp="1")
        ReportBuilder(filled_db, directory).build(stamp="2")
        latest = directory / "son-rapor.html"
        assert latest.exists()
        assert "Engellenen hesaplar" in latest.read_text(encoding="utf-8")

    def test_csv_can_be_disabled(self, filled_db, tmp_path):
        paths = ReportBuilder(filled_db, tmp_path / "rapor").build(csv_report=False)
        assert paths.blocks_csv is None
        assert paths.html is not None

    def test_summary_lines_are_included(self, filled_db, tmp_path):
        paths = ReportBuilder(filled_db, tmp_path / "rapor").build(
            summary_lines=["DURDU: CAPTCHA göründü"]
        )
        assert "CAPTCHA göründü" in paths.html.read_text(encoding="utf-8")
