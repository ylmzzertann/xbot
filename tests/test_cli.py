"""Komut satiri arayuzu testleri.

Tarayici gerektiren komutlar (login, run, check-selectors, sync-whitelist)
burada YALNIZCA tarayici acmadan verdikleri kararlar icin test edilir; gercek
tarayici testleri elle yapilir (README -> "Elle test listesi").
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone

import pytest
import yaml
from typer.testing import CliRunner

from xbot.cli import app
from xbot.models import Decision, Level, Match, Severity, Tweet
from xbot.storage import Storage

runner = CliRunner()

PLAYWRIGHT_INSTALLED = importlib.util.find_spec("playwright") is not None
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def config_file(tmp_path, data_dir):
    """Depodaki gercek listeleri kullanan gecici bir config.yaml."""
    data = {
        "search_queries": ["Okan Buruk"],
        "target_names": ["okan", "buruk"],
        "mode": "dry-run",
        "paths": {
            "profile_dir": str(tmp_path / "profil"),
            "db_path": str(tmp_path / "veri" / "xbot.sqlite3"),
            "log_dir": str(tmp_path / "kayit"),
            "screenshot_dir": str(tmp_path / "kayit" / "ekran"),
            "report_dir": str(tmp_path / "rapor"),
        },
        "files": {
            "profanity": str(data_dir / "profanity.txt"),
            "allowlist_words": str(data_dir / "allowlist_words.txt"),
            "allowlist_phrases": str(data_dir / "allowlist_phrases.txt"),
            "positive_context": str(data_dir / "positive_context.txt"),
            "whitelist": str(tmp_path / "whitelist.txt"),
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    (tmp_path / "whitelist.txt").write_text("# beyaz liste\n", encoding="utf-8")
    return path


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "veri" / "xbot.sqlite3"


def seed_block(db_path, *, username="kotu_hesap", text="siktir git") -> int:
    tweet = Tweet(tweet_id="1", username=username, text=text, created_at=NOW)
    decision = Decision(
        tweet=tweet,
        level=Level.HIGH,
        matches=(Match("profanity", "siktir", Severity.STRONG, "siktir"),),
        reasons=("güçlü eşleşme",),
    )
    with Storage(db_path) as storage:
        return storage.record_block(tweet, decision)


def seed_suspect(db_path, *, username="belirsiz", text="amk gol") -> None:
    tweet = Tweet(tweet_id="2", username=username, text=text, created_at=NOW)
    decision = Decision(
        tweet=tweet,
        level=Level.SUSPECT,
        matches=(Match("profanity", "amk", Severity.AMBIGUOUS, "amk"),),
        reasons=("belirsiz ifade",),
    )
    with Storage(db_path) as storage:
        storage.add_suspect(tweet, decision)


def run(config_file, *args):
    return runner.invoke(app, ["--config", str(config_file), *args])


# --------------------------------------------------------------------------
# tespit komutlari
# --------------------------------------------------------------------------


class TestCheck:
    def test_high_decision(self, config_file):
        result = run(config_file, "check", "siktir git okan buruk")
        assert result.exit_code == 0
        assert "YÜKSEK" in result.output
        assert "ENGELLENİRDİ" in result.output

    def test_clean_decision(self, config_file):
        result = run(config_file, "check", "sıkıntı yok kardeşim")
        assert result.exit_code == 0
        assert "TEMİZ" in result.output

    def test_suspect_decision(self, config_file):
        result = run(config_file, "check", "amk gol")
        assert result.exit_code == 0
        assert "ŞÜPHELİ" in result.output

    def test_short_output(self, config_file):
        result = run(config_file, "check", "--kisa", "orospu")
        assert result.exit_code == 0
        assert result.output.strip() == "YÜKSEK"

    def test_missing_text(self, config_file):
        assert run(config_file, "check").exit_code == 1

    def test_multiple_words_are_joined(self, config_file):
        result = run(config_file, "check", "siktir", "git")
        assert result.exit_code == 0
        assert "YÜKSEK" in result.output


class TestCheckFile:
    def test_file_is_processed(self, config_file, tmp_path):
        sample = tmp_path / "ornek.txt"
        sample.write_text(
            "# yorum satiri\nsiktir git\nsıkıntı yok\namk gol\n\n", encoding="utf-8"
        )
        result = run(config_file, "check-file", str(sample))
        assert result.exit_code == 0
        assert "1 temiz" in result.output
        assert "1 şüpheli" in result.output
        assert "1 yüksek" in result.output

    def test_only_flagged_filter(self, config_file, tmp_path):
        sample = tmp_path / "ornek.txt"
        sample.write_text("sıkıntı yok\nsiktir\n", encoding="utf-8")
        result = run(config_file, "check-file", "--sadece-isaretli", str(sample))
        assert result.exit_code == 0
        assert "sıkıntı yok" not in result.output

    def test_missing_file(self, config_file, tmp_path):
        result = run(config_file, "check-file", str(tmp_path / "yok.txt"))
        assert result.exit_code == 1
        assert "bulunamadı" in result.output


class TestWordsAndConfig:
    def test_words_summary(self, config_file):
        result = run(config_file, "words")
        assert result.exit_code == 0
        assert "Küfür kökü" in result.output

    def test_words_listing(self, config_file):
        result = run(config_file, "words", "--listele")
        assert result.exit_code == 0
        assert "siktir" in result.output

    def test_config_show(self, config_file):
        result = run(config_file, "config-show")
        assert result.exit_code == 0
        assert "dry-run" in result.output
        assert "yerinde" in result.output

    def test_invalid_config_exits_with_code_2(self, tmp_path):
        bad = tmp_path / "config.yaml"
        bad.write_text("mode: engelle\n", encoding="utf-8")
        result = run(bad, "config-show")
        assert result.exit_code == 2
        assert "Ayar hatası" in result.output

    def test_missing_config(self, tmp_path):
        assert run(tmp_path / "yok.yaml", "check", "test").exit_code == 2


# --------------------------------------------------------------------------
# kayit/rapor komutlari
# --------------------------------------------------------------------------


class TestBlockRecords:
    def test_empty_list(self, config_file):
        result = run(config_file, "list-blocked")
        assert result.exit_code == 0
        assert "kaydı yok" in result.output

    def test_list_shows_evidence(self, config_file, db_path):
        seed_block(db_path)
        result = run(config_file, "list-blocked")
        assert result.exit_code == 0
        assert "@kotu_hesap" in result.output
        assert "siktir" in result.output
        assert "Engeli kaldırmak" in result.output

    def test_mark_unblocked(self, config_file, db_path):
        block_id = seed_block(db_path)
        result = run(config_file, "mark-unblocked", str(block_id), "--not", "yanlıştı")
        assert result.exit_code == 0
        assert "geri alındı" in result.output
        with Storage(db_path) as storage:
            assert storage.is_blocked("kotu_hesap") is False

    def test_mark_unblocked_unknown_id(self, config_file, db_path):
        seed_block(db_path)
        result = run(config_file, "mark-unblocked", "999")
        assert result.exit_code == 1
        assert "bulunamadı" in result.output


class TestDoctor:
    def test_doctor_reports_setup(self, config_file):
        result = run(config_file, "doctor")
        assert "Kurulum kontrolü" in result.output
        assert "Python 3.11+" in result.output
        assert "Kelime listeleri" in result.output
        # Playwright kurulu olsa da olmasa da komut bir karar vermeli
        assert result.exit_code in (0, 2)

    def test_doctor_detects_missing_wordlists(self, tmp_path):
        data = {
            "files": {"profanity": str(tmp_path / "yok.txt")},
            "paths": {"log_dir": str(tmp_path / "kayit"), "db_path": str(tmp_path / "v.sqlite3")},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        result = run(path, "doctor")
        assert result.exit_code == 2
        assert "Kelime listeleri" in result.output


class TestStats:
    def test_stats_on_empty_database(self, config_file):
        result = run(config_file, "stats")
        assert result.exit_code == 0
        assert "İstatistikler" in result.output
        assert "hiç çalışmadı" in result.output

    def test_stats_with_data(self, config_file, db_path):
        seed_block(db_path)
        seed_suspect(db_path)
        result = run(config_file, "stats")
        assert result.exit_code == 0
        assert "Engellenen hesap" in result.output
        assert "Limit durumu" in result.output


class TestReport:
    def test_report_creates_files(self, config_file, tmp_path, db_path):
        seed_block(db_path)
        seed_suspect(db_path)
        result = run(config_file, "report")
        assert result.exit_code == 0
        assert "Rapor:" in result.output
        files = list((tmp_path / "rapor").glob("*"))
        names = {path.name for path in files}
        assert "son-rapor.html" in names
        assert any(name.startswith("engellenenler-") for name in names)
        assert any(name.startswith("supheliler-") for name in names)

    def test_report_without_csv(self, config_file, tmp_path, db_path):
        seed_block(db_path)
        result = run(config_file, "report", "--csv-yok")
        assert result.exit_code == 0
        assert not list((tmp_path / "rapor").glob("*.csv"))


class TestTaskCommand:
    def test_prints_windows_and_cron_lines(self, config_file):
        result = run(config_file, "task-command", "--dakika", "30")
        assert result.exit_code == 0
        assert "schtasks /Create" in result.output
        assert "/MO 30" in result.output
        assert "crontab" in result.output or "*/30" in result.output

    def test_auto_variant_uses_auto_script(self, config_file):
        result = run(config_file, "task-command", "--auto")
        assert "xbot_auto.cmd" in result.output


# --------------------------------------------------------------------------
# tarayici komutlari: tarayici ACMADAN verilen kararlar
# --------------------------------------------------------------------------


class TestBrowserCommandGuards:
    def test_run_without_queries_is_usage_error(self, tmp_path, data_dir):
        data = {
            "search_queries": [],
            "files": {"profanity": str(data_dir / "profanity.txt")},
            "paths": {"log_dir": str(tmp_path / "kayit")},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        result = run(path, "run")
        assert result.exit_code == 1
        assert "search_queries" in result.output

    def test_auto_and_dry_run_together_is_refused(self, config_file):
        result = run(config_file, "run", "--auto", "--dry-run")
        assert result.exit_code == 1
        assert "birlikte kullanılamaz" in result.output

    def test_check_selectors_needs_a_query(self, tmp_path, data_dir):
        data = {
            "search_queries": [],
            "files": {"profanity": str(data_dir / "profanity.txt")},
            "paths": {"log_dir": str(tmp_path / "kayit")},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        result = run(path, "check-selectors")
        assert result.exit_code == 1
        assert "--query" in result.output

    def test_review_without_suspects_does_not_open_browser(self, config_file):
        result = run(config_file, "review")
        assert result.exit_code == 0
        assert "Bekleyen şüpheli tweet yok" in result.output

    @pytest.mark.skipif(
        PLAYWRIGHT_INSTALLED,
        reason="Playwright kurulu: bu test gerçek tarayıcı açmamak için atlanır.",
    )
    def test_login_without_playwright_explains_installation(self, config_file):
        result = run(config_file, "login")
        assert result.exit_code == 2
        assert "playwright install chromium" in result.output


class TestHelp:
    def test_help_is_turkish(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "küfür" in result.output

    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code != 0
        assert "check" in result.output

    def test_every_command_is_listed(self):
        result = runner.invoke(app, ["--help"])
        for command in (
            "check",
            "check-file",
            "words",
            "config-show",
            "login",
            "check-selectors",
            "run",
            "review",
            "list-blocked",
            "mark-unblocked",
            "stats",
            "report",
            "sync-whitelist",
            "task-command",
        ):
            assert command in result.output
