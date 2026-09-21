"""config.yaml okuma ve dogrulama testleri."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from xbot.config import AppConfig, ConfigError, find_config_path, load_config


class TestDefaults:
    def test_minimal_config_gets_safe_defaults(self, project_root):
        config = AppConfig.from_dict({}, base_dir=project_root)
        assert config.mode == "dry-run"
        assert config.is_dry_run is True
        assert config.time_window_minutes == 60
        assert config.limits.per_hour == 10
        assert config.limits.per_day == 40
        assert config.delays.between_actions == (8.0, 25.0)
        assert config.delays.between_scrolls == (2.0, 5.0)
        assert config.headless is False  # ilk calistirmalarda gorunur
        assert config.max_scrolls_per_query == 15

    def test_detection_defaults(self, project_root):
        detection = AppConfig.from_dict({}, base_dir=project_root).detection
        assert detection.high_requires_target is False
        assert detection.ambiguous_with_target == "high"
        assert detection.mild_with_target == "high"
        assert detection.positive_context_guard is True
        assert detection.min_root_length_for_glue == 6

    def test_paths_are_resolved_against_base_dir(self, project_root):
        config = AppConfig.from_dict({}, base_dir=project_root)
        assert config.paths.profile_dir == project_root / ".profile"
        assert config.files.profanity == project_root / "data" / "profanity.txt"

    def test_absolute_paths_are_kept(self, project_root, tmp_path):
        config = AppConfig.from_dict(
            {"paths": {"log_dir": str(tmp_path / "kayit")}}, base_dir=project_root
        )
        assert config.paths.log_dir == tmp_path / "kayit"

    def test_queries_are_deduplicated_and_trimmed(self, project_root):
        config = AppConfig.from_dict(
            {"search_queries": [" Okan Buruk ", "Okan Buruk", "Galatasaray"]},
            base_dir=project_root,
        )
        assert config.search_queries == ("Okan Buruk", "Galatasaray")


class TestValidation:
    def test_unknown_top_level_key(self, project_root):
        with pytest.raises(ConfigError, match="tanınmayan ayar"):
            AppConfig.from_dict({"sarch_queries": []}, base_dir=project_root)

    def test_unknown_nested_key(self, project_root):
        with pytest.raises(ConfigError, match="limits"):
            AppConfig.from_dict({"limits": {"per_minute": 3}}, base_dir=project_root)

    def test_invalid_mode(self, project_root):
        with pytest.raises(ConfigError, match="mode"):
            AppConfig.from_dict({"mode": "engelle"}, base_dir=project_root)

    def test_string_instead_of_list(self, project_root):
        with pytest.raises(ConfigError, match="liste olmalı"):
            AppConfig.from_dict({"search_queries": "Okan"}, base_dir=project_root)

    def test_empty_item_in_list(self, project_root):
        with pytest.raises(ConfigError, match="boş olmayan"):
            AppConfig.from_dict({"target_names": ["okan", "  "]}, base_dir=project_root)

    def test_negative_limit(self, project_root):
        with pytest.raises(ConfigError, match="en az 0"):
            AppConfig.from_dict({"limits": {"per_hour": -1}}, base_dir=project_root)

    def test_bool_instead_of_int(self, project_root):
        with pytest.raises(ConfigError, match="tam sayı"):
            AppConfig.from_dict({"time_window_minutes": True}, base_dir=project_root)

    def test_reversed_delay_range(self, project_root):
        with pytest.raises(ConfigError, match="alt sınır üst sınırdan"):
            AppConfig.from_dict(
                {"delays": {"between_actions": [25, 8]}}, base_dir=project_root
            )

    def test_delay_needs_two_items(self, project_root):
        with pytest.raises(ConfigError, match="iki öğeli"):
            AppConfig.from_dict(
                {"delays": {"between_scrolls": [3]}}, base_dir=project_root
            )

    def test_invalid_ambiguous_action(self, project_root):
        with pytest.raises(ConfigError, match="ambiguous_with_target"):
            AppConfig.from_dict(
                {"detection": {"ambiguous_with_target": "engelle"}},
                base_dir=project_root,
            )

    def test_invalid_log_level(self, project_root):
        with pytest.raises(ConfigError, match="logging.level"):
            AppConfig.from_dict({"logging": {"level": "HEPSI"}}, base_dir=project_root)

    def test_headless_must_be_bool(self, project_root):
        with pytest.raises(ConfigError, match="true veya false"):
            AppConfig.from_dict({"headless": "evet"}, base_dir=project_root)


class TestLoadConfig:
    def test_load_from_file(self, tmp_path, project_root):
        data = {
            "search_queries": ["Okan Buruk"],
            "mode": "dry-run",
            "files": {"profanity": str(project_root / "data" / "profanity.txt")},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        config = load_config(path)
        assert config.search_queries == ("Okan Buruk",)
        assert config.source_path == path
        assert config.base_dir == tmp_path.resolve()

    def test_missing_file_message_is_helpful(self, tmp_path):
        with pytest.raises(ConfigError, match="Ayar dosyası bulunamadı"):
            load_config(tmp_path / "yok.yaml")

    def test_broken_yaml(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("mode: [dry-run\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="YAML"):
            load_config(path)

    def test_empty_file(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="boş"):
            load_config(path)

    def test_example_config_is_valid(self, project_root):
        """Depodaki ornek dosya her zaman gecerli olmali."""
        config = load_config(project_root / "config.example.yaml")
        assert config.mode == "dry-run"
        assert config.search_queries
        assert config.files.missing() == []

    def test_find_config_path_prefers_explicit(self, tmp_path):
        target = tmp_path / "ozel.yaml"
        assert find_config_path(target) == target.resolve()


class TestHelpers:
    def test_ensure_dirs_creates_folders(self, tmp_path):
        config = AppConfig.from_dict(
            {
                "paths": {
                    "profile_dir": "profil",
                    "log_dir": "kayit",
                    "screenshot_dir": "kayit/ekran",
                    "report_dir": "rapor",
                    "db_path": "veri/xbot.sqlite3",
                }
            },
            base_dir=tmp_path,
        )
        config.ensure_dirs()
        for folder in ("profil", "kayit", "kayit/ekran", "rapor", "veri"):
            assert (tmp_path / folder).is_dir()

    def test_summary_rows_are_printable(self, app_config: AppConfig):
        rows = app_config.summary_rows()
        assert all(isinstance(key, str) and isinstance(value, str) for key, value in rows)
        assert any("dry-run" in value for _key, value in rows)

    def test_missing_lists_are_reported(self, tmp_path):
        config = AppConfig.from_dict(
            {"files": {"profanity": "yok/olmayan.txt"}}, base_dir=tmp_path
        )
        missing = config.files.missing()
        assert Path(tmp_path / "yok" / "olmayan.txt") in missing
