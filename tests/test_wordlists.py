"""Kelime listesi dosyalarinin okunmasi ve dogrulanmasi."""

from __future__ import annotations

import pytest

from xbot.models import Severity
from xbot.wordlists import (
    WordListError,
    load_profanity_entries,
    load_profanity_patterns,
    load_word_list,
    parse_profanity_line,
    read_lines,
)


def write(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestReadLines:
    def test_comments_and_blank_lines_are_ignored(self, tmp_path):
        path = write(tmp_path, "l.txt", "# başlık\n\n  orospu \n\n# son\n")
        assert read_lines(path) == [(3, "orospu")]

    def test_inline_comment_is_stripped(self, tmp_path):
        path = write(tmp_path, "l.txt", "amk | ambiguous # sevinç de olabilir\n")
        assert read_lines(path) == [(1, "amk | ambiguous")]

    def test_hash_inside_word_is_kept(self, tmp_path):
        path = write(tmp_path, "l.txt", "a#k\n")
        assert read_lines(path) == [(1, "a#k")]

    def test_bom_is_handled(self, tmp_path):
        path = tmp_path / "bom.txt"
        path.write_bytes("﻿siktir\n".encode("utf-8"))
        assert read_lines(path) == [(1, "siktir")]

    def test_missing_file_raises_turkish_error(self, tmp_path):
        with pytest.raises(WordListError, match="bulunamadı"):
            read_lines(tmp_path / "yok.txt")


class TestLoadWordList:
    def test_duplicates_removed_order_kept(self, tmp_path):
        path = write(tmp_path, "w.txt", "bir\niki\nbir\n")
        assert load_word_list(path) == ("bir", "iki")


class TestParseProfanityLine:
    def test_default_severity_is_strong(self):
        entry = parse_profanity_line("orospu")
        assert entry.severity is Severity.STRONG
        assert entry.exact is False
        assert entry.keep_i is False

    def test_flags_are_parsed(self):
        entry = parse_profanity_line("amk | ambiguous, exact", 7)
        assert entry.severity is Severity.AMBIGUOUS
        assert entry.exact is True
        assert entry.line_no == 7

    def test_keep_i_flag(self):
        assert parse_profanity_line("sik | strong, keep_i").keep_i is True

    def test_unknown_flag_raises(self):
        with pytest.raises(WordListError, match="bilinmeyen bayrak"):
            parse_profanity_line("orospu | cok_kotu", 3)

    def test_two_severity_flags_raise(self):
        with pytest.raises(WordListError, match="tek bir ağırlık bayrağı"):
            parse_profanity_line("orospu | mild, strong", 4)

    def test_empty_root_raises(self):
        with pytest.raises(WordListError, match="kök boş olamaz"):
            parse_profanity_line("| mild", 5)

    def test_flags_are_case_insensitive(self):
        assert parse_profanity_line("salak | MILD").severity is Severity.MILD


class TestLoadProfanity:
    def test_duplicate_roots_are_ignored(self, tmp_path):
        path = write(tmp_path, "p.txt", "orospu\norospu | mild\nsalak | mild\n")
        entries = load_profanity_entries(path)
        assert [e.raw for e in entries] == ["orospu", "salak"]
        assert entries[0].severity is Severity.STRONG  # ilk tanim gecerli

    def test_empty_list_raises(self, tmp_path):
        path = write(tmp_path, "p.txt", "# sadece yorum\n")
        with pytest.raises(WordListError, match="boş"):
            load_profanity_entries(path)

    def test_patterns_are_built(self, tmp_path):
        path = write(tmp_path, "p.txt", "göt oğlanı\n")
        patterns = load_profanity_patterns(path)
        assert patterns[0].form.folded == "gotoglani"
        assert patterns[0].multiword is True


class TestProjectLists:
    """Proje ile gelen gercek listeler bozuk olmasin."""

    def test_default_profanity_list_loads(self, data_dir):
        entries = load_profanity_entries(data_dir / "profanity.txt")
        assert len(entries) > 50
        severities = {e.severity for e in entries}
        assert severities == {Severity.STRONG, Severity.MILD, Severity.AMBIGUOUS}

    def test_default_allowlists_load(self, data_dir):
        assert len(load_word_list(data_dir / "allowlist_words.txt")) > 10
        assert len(load_word_list(data_dir / "allowlist_phrases.txt")) > 5
        assert len(load_word_list(data_dir / "positive_context.txt")) > 10

    def test_whitelist_may_be_empty(self, data_dir):
        assert load_word_list(data_dir / "whitelist.txt") == ()
