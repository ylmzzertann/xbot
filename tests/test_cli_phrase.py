"""'phrase' ve 'blocked-tweets' komutlarinin etkilesimli akis testleri.

Gercek tarayici yerine sahte bir BrowserApp kullanilir; ama engelleme karari,
limitler, beyaz liste, SQLite kayitlari ve tweet dosyasi GERCEK kodla calisir.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import yaml
from typer.testing import CliRunner

import xbot.cli as cli_module
from xbot.actions import Blocker
from xbot.cli import app
from xbot.config import Delays, Limits
from xbot.detector.phrase import PhraseDetector
from xbot.evidence import BlockedTweetLog
from xbot.models import Tweet
from xbot.phrase_hunt import PhraseSearchResult, match_tweets, search_query_for
from xbot.ratelimit import RateLimiter
from xbot.scraper import ScrapeResult
from xbot.storage import Storage

runner = CliRunner()
NOW = datetime.now(timezone.utc)


def tweet(tweet_id: str, username: str, text: str) -> Tweet:
    return Tweet(
        tweet_id=tweet_id,
        username=username,
        text=text,
        created_at=NOW - timedelta(minutes=5),
    )


SEARCH_RESULTS = [
    tweet("1", "kizgin1", "Okan istifa artık yeter"),
    tweet("2", "kizgin2", "OKAN İSTİFA!!! siktir git"),
    tweet("3", "kizgin2", "okan istifa diyorum hala"),
    tweet("4", "dostum", "okan istifa etsin bence"),
    tweet("5", "alakasiz", "bugün maç var"),
]


class FakeUi:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def open_tweet_menu(self, tweet_id, url=None):
        self.opened.append(tweet_id)

    def click_block(self):
        pass

    def confirm_block(self):
        pass

    def verify_blocked(self, username):
        return True

    def close_menu(self):
        pass


class FakeBrowserApp:
    """Tarayici yerine gecer; engelleme icin GERCEK Blocker kullanir."""

    instances: list["FakeBrowserApp"] = []
    results = SEARCH_RESULTS

    def __init__(self, services, *, headless=None) -> None:
        self.services = services
        self.ui = FakeUi()
        self.searched: list[str] = []
        FakeBrowserApp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def detect_handle(self) -> str:
        return "benim_hesap"

    def find_phrase(self, phrase, *, minutes=None, whole_word=False, max_scrolls=None):
        self.searched.append(phrase)
        detector = PhraseDetector([phrase], whole_word=whole_word)
        return PhraseSearchResult(
            phrase=phrase,
            query=search_query_for(phrase),
            matches=match_tweets(self.results, detector),
            scrape=ScrapeResult(query=phrase, total_seen=len(self.results)),
        )

    def block_single(self, tw, decision, *, mode="review", evidence_tweets=None, reason=None):
        limiter = RateLimiter(
            self.services.config.limits,
            Delays(between_actions=(0, 0), between_scrolls=(0, 0)),
            storage=self.services.storage,
            sleeper=lambda _s: None,
        )
        blocker = Blocker(
            self.ui,
            storage=self.services.storage,
            whitelist=self.services.whitelist,
            limiter=limiter,
            dry_run=False,
            tweet_log=self.services.tweet_log,
        )
        return blocker.block(
            tw, decision, mode=mode, evidence_tweets=evidence_tweets, reason=reason
        )


@pytest.fixture(autouse=True)
def fake_browser(monkeypatch):
    FakeBrowserApp.instances = []
    FakeBrowserApp.results = SEARCH_RESULTS
    monkeypatch.setattr(cli_module, "BrowserApp", FakeBrowserApp)
    return FakeBrowserApp


def write_config(tmp_path, data_dir, *, per_hour=10, per_day=40):
    data = {
        "search_queries": ["Okan Buruk"],
        "target_names": ["okan", "buruk"],
        "limits": {"per_hour": per_hour, "per_day": per_day},
        "delays": {"between_actions": [0, 0], "between_scrolls": [0, 0]},
        "paths": {
            "profile_dir": str(tmp_path / "profil"),
            "db_path": str(tmp_path / "veri" / "xbot.sqlite3"),
            "log_dir": str(tmp_path / "kayit"),
            "screenshot_dir": str(tmp_path / "kayit" / "ekran"),
            "report_dir": str(tmp_path / "rapor"),
            "blocked_tweets": str(tmp_path / "kayitlar" / "engellenen_tweetler.csv"),
        },
        "files": {
            "profanity": str(data_dir / "profanity.txt"),
            "allowlist_words": str(data_dir / "allowlist_words.txt"),
            "allowlist_phrases": str(data_dir / "allowlist_phrases.txt"),
            "positive_context": str(data_dir / "positive_context.txt"),
            "whitelist": str(tmp_path / "whitelist.txt"),
        },
    }
    (tmp_path / "whitelist.txt").write_text("# beyaz liste\ndostum\n", encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def config_file(tmp_path, data_dir):
    return write_config(tmp_path, data_dir)


@pytest.fixture
def tweet_file(tmp_path):
    return BlockedTweetLog(tmp_path / "kayitlar" / "engellenen_tweetler.csv")


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "veri" / "xbot.sqlite3"


def run(config_file, *args, input_text=""):
    return runner.invoke(app, ["--config", str(config_file), *args], input=input_text)


def flat(text: str) -> str:
    """Rich'in satir kaydirmasini ve kenarliklarini yok sayarak karsilastirma icin."""
    return "".join(ch for ch in text if not ch.isspace() and ch not in "│┃|")


def blocked_users(db_path) -> list[str]:
    with Storage(db_path) as storage:
        return sorted(record.username for record in storage.recent_blocks(50))


class TestShowBeforeBlocking:
    def test_matches_are_listed_before_any_block(self, config_file, db_path):
        result = run(config_file, "phrase", "okan istifa", input_text="v\n")
        assert result.exit_code == 0, result.output
        out = result.output
        assert "@kizgin1" in out and "@kizgin2" in out and "@dostum" in out
        assert "@alakasiz" not in out  # ifadeyi icermiyor
        assert "(+1 tweet daha)" in out  # kizgin2'nin ikinci tweeti
        assert "beyaz listede" in out
        assert "2 hesap engellenecek" in out
        assert "Vazgeçildi" in out
        assert blocked_users(db_path) == []

    def test_list_only_never_asks(self, config_file, db_path):
        result = run(config_file, "phrase", "okan istifa", "--sadece-goster")
        assert result.exit_code == 0
        assert "@kizgin1" in result.output
        assert "evet" not in result.output
        assert blocked_users(db_path) == []

    def test_phrase_is_asked_when_not_given(self, config_file, fake_browser):
        result = run(config_file, "phrase", input_text="okan istifa\nv\n")
        assert result.exit_code == 0, result.output
        assert fake_browser.instances[0].searched == ["okan istifa"]
        assert "@kizgin1" in result.output

    def test_no_matches(self, config_file, db_path):
        result = run(config_file, "phrase", "bulunmayan ifade")
        assert result.exit_code == 0
        assert "içeren tweet bulunamadı" in result.output
        assert "5 tweet incelendi" in result.output

    def test_invalid_phrase(self, config_file):
        result = run(config_file, "phrase", "a")
        assert result.exit_code == 1
        assert "çok kısa" in result.output

    def test_short_phrase_warning(self, config_file):
        result = run(config_file, "phrase", "ok", input_text="v\n")
        assert "kısa bir ifade" in result.output


class TestApproval:
    def test_approve_all_blocks_and_saves_tweets(self, config_file, db_path, tweet_file):
        result = run(config_file, "phrase", "okan istifa", input_text="e\nevet\n")
        assert result.exit_code == 0, result.output
        assert "2 hesap engellendi" in result.output
        assert blocked_users(db_path) == ["kizgin1", "kizgin2"]  # dostum beyaz listede

        rows = tweet_file.read()
        assert [(row["hesap"], row["tweet_id"]) for row in rows] == [
            ("kizgin1", "1"),
            ("kizgin2", "2"),
            ("kizgin2", "3"),  # ayni hesabin tum eslesen tweetleri
        ]
        assert all(row["sebep"] == 'ifade: "okan istifa"' for row in rows)
        assert all(row["mod"] == "phrase" for row in rows)
        assert flat(str(tweet_file.path)) in flat(result.output)

    def test_final_confirmation_must_be_evet(self, config_file, db_path, tweet_file):
        result = run(config_file, "phrase", "okan istifa", input_text="e\nhayır\n")
        assert result.exit_code == 0
        assert "Onay verilmedi" in result.output
        assert blocked_users(db_path) == []
        assert tweet_file.read() == []

    def test_exclude_some_numbers(self, config_file, db_path):
        result = run(config_file, "phrase", "okan istifa", input_text="ç\n1\ne\nevet\n")
        assert result.exit_code == 0, result.output
        assert "Çıkarılanlar: 1" in result.output
        assert blocked_users(db_path) == ["kizgin2"]

    def test_bad_number_is_asked_again(self, config_file, db_path):
        result = run(
            config_file, "phrase", "okan istifa", input_text="ç\n99\nç\n2\ne\nevet\n"
        )
        assert result.exit_code == 0, result.output
        assert "99 numaralı satır yok" in result.output
        assert blocked_users(db_path) == ["kizgin1"]

    def test_excluding_everyone_blocks_nothing(self, config_file, db_path):
        result = run(config_file, "phrase", "okan istifa", input_text="ç\n1,2\n")
        assert result.exit_code == 0
        assert "Engellenecek hesap kalmadı" in result.output
        assert blocked_users(db_path) == []

    def test_empty_answer_means_cancel(self, config_file, db_path):
        result = run(config_file, "phrase", "okan istifa", input_text="\n")
        assert result.exit_code == 0
        assert "Vazgeçildi" in result.output
        assert blocked_users(db_path) == []

    def test_already_blocked_account_is_not_blocked_twice(self, config_file, db_path):
        run(config_file, "phrase", "okan istifa", input_text="e\nevet\n")
        result = run(config_file, "phrase", "okan istifa", input_text="v\n")
        assert "zaten engelli" in result.output
        assert "0 hesap engellenecek" in result.output

    def test_run_is_recorded_in_stats(self, config_file, db_path):
        run(config_file, "phrase", "okan istifa", input_text="e\nevet\n")
        with Storage(db_path) as storage:
            last = storage.last_runs(1)[0]
        assert last["mode"] == "phrase"
        assert last["blocked"] == 2
        assert last["queries"] == "okan istifa"


class TestLimits:
    def test_limit_defers_rest_to_review(self, tmp_path, data_dir, db_path):
        config_file = write_config(tmp_path, data_dir, per_hour=1)
        result = run(config_file, "phrase", "okan istifa", input_text="e\nevet\n")
        assert result.exit_code == 0, result.output
        assert "şimdi 1 hesap engellenebilir" in result.output
        assert blocked_users(db_path) == ["kizgin1"]
        with Storage(db_path) as storage:
            pending = storage.pending_suspects()
        assert [record.username for record in pending] == ["kizgin2"]
        assert pending[0].rules == 'ifade: "okan istifa"'

    def test_full_limit_blocks_nothing(self, tmp_path, data_dir, db_path):
        config_file = write_config(tmp_path, data_dir, per_hour=0)
        result = run(config_file, "phrase", "okan istifa", input_text="e\n")
        assert result.exit_code == 0, result.output
        assert "Limit dolu" in result.output
        assert blocked_users(db_path) == []


class TestBlockedTweetsCommand:
    def test_empty(self, config_file):
        result = run(config_file, "blocked-tweets")
        assert result.exit_code == 0
        assert "Henüz kayıt yok" in result.output

    def test_lists_saved_tweets(self, config_file):
        run(config_file, "phrase", "okan istifa", input_text="e\nevet\n")
        result = run(config_file, "blocked-tweets")
        assert result.exit_code == 0, result.output
        assert "@kizgin2" in result.output
        assert "diyorum hala" in result.output  # tablo hucresi satira bolunebilir
        assert "engellenen_tweetler.csv" in flat(result.output)
