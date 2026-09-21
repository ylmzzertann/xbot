"""Kok eslestirme motoru testleri (Matcher)."""

from __future__ import annotations

import pytest

from xbot.detector.matcher import Matcher, make_pattern
from xbot.detector.normalizer import normalize_text
from xbot.models import Severity


def rules(matcher: Matcher, text: str) -> list[str]:
    """Metinde eslesen kok adlarini dondurur."""
    return [m.pattern.raw for m in matcher.find(normalize_text(text))]


def matches(matcher: Matcher, text: str):
    return matcher.find(normalize_text(text))


class TestLiteralMatching:
    def test_substring_match(self):
        matcher = Matcher([make_pattern("orospu")])
        assert rules(matcher, "orospunun evladı") == ["orospu"]

    def test_exact_flag_requires_whole_word(self):
        matcher = Matcher([make_pattern("amk", Severity.AMBIGUOUS, exact=True)])
        assert rules(matcher, "amk") == ["amk"]
        assert rules(matcher, "amkkkk") == ["amk"]  # tekrarlar sadelesir
        assert rules(matcher, "adamki geldi") == []

    def test_multiword_pattern_matches_across_words(self):
        matcher = Matcher([make_pattern("amına koyayım")])
        assert rules(matcher, "senin amına koyayım") == ["amına koyayım"]
        assert rules(matcher, "aminakoyayim") == ["amına koyayım"]

    def test_single_word_pattern_does_not_match_across_words(self):
        # "klasik tirat" -> birlesik metinde "siktir" olusur ama tek kelimelik
        # kokler birlesik gecise girmez.
        matcher = Matcher([make_pattern("siktir", keep_i=True)])
        assert rules(matcher, "klasik tirat") == []
        assert rules(matcher, "siktir") == ["siktir"]


class TestDotlessIHandling:
    def test_keep_i_separates_innocent_word(self):
        matcher = Matcher([make_pattern("sik", exact=True, keep_i=True)])
        assert rules(matcher, "sik") == ["sik"]
        assert rules(matcher, "sık") == []  # "sık sık" masum
        assert rules(matcher, "SIK") == []  # buyuk I -> noktasiz i
        assert rules(matcher, "SİK") == ["sik"]

    def test_without_keep_i_both_spellings_match(self):
        matcher = Matcher([make_pattern("amına", exact=True)])
        assert rules(matcher, "amına") == ["amına"]
        assert rules(matcher, "amina") == ["amına"]


class TestObfuscation:
    def test_mask_character_matches_any_letter(self):
        matcher = Matcher([make_pattern("siktir", keep_i=True)])
        found = matches(matcher, "s*ktir")
        assert [m.pattern.raw for m in found] == ["siktir"]
        assert found[0].obfuscated is True

    def test_too_many_masks_are_rejected(self):
        matcher = Matcher([make_pattern("orospu")])
        assert rules(matcher, "or*spu") == ["orospu"]  # 1 joker: kabul
        assert rules(matcher, "or*sp*") == []  # 2 joker: cok fazla

    def test_spaced_letters_match_via_run(self):
        matcher = Matcher([make_pattern("orospu")])
        found = matches(matcher, "o r o s p u seni")
        assert [m.pattern.raw for m in found] == ["orospu"]
        assert found[0].source == "run"
        assert found[0].obfuscated is True

    def test_short_exact_root_matches_in_run(self):
        matcher = Matcher([make_pattern("amk", Severity.AMBIGUOUS, exact=True)])
        assert rules(matcher, "a m k") == ["amk"]

    def test_leet_digits(self):
        matcher = Matcher([make_pattern("siktir", keep_i=True)])
        assert rules(matcher, "s1kt1r git") == ["siktir"]


class TestAllowlist:
    def test_allow_word_covering_root_suppresses_match(self):
        matcher = Matcher([make_pattern("test")], ["testere"])
        assert rules(matcher, "testere aldım") == []
        assert rules(matcher, "test yaptım") == ["test"]

    def test_allow_word_must_cover_the_whole_root(self):
        # "tes" koku kapsamaz, eslesme silinmez
        matcher = Matcher([make_pattern("test")], ["tes"])
        assert rules(matcher, "test") == ["test"]

    def test_real_case_gotur(self):
        matcher = Matcher([make_pattern("göt")], ["götür"])
        assert rules(matcher, "seni maça götürdüm") == []
        assert rules(matcher, "göt herif") == ["göt"]

    def test_allow_phrase_suppresses_root_in_phrase(self):
        matcher = Matcher(
            [make_pattern("eşek", Severity.AMBIGUOUS)],
            allow_phrases=["eşek arısı"],
        )
        assert rules(matcher, "eşek arısı soktu") == []
        assert rules(matcher, "eşek herif") == ["eşek"]

    def test_allow_phrase_only_suppresses_roots_inside_it(self):
        matcher = Matcher(
            [make_pattern("eşek", Severity.AMBIGUOUS), make_pattern("orospu")],
            allow_phrases=["eşek arısı"],
        )
        assert rules(matcher, "eşek arısı ve orospu") == ["orospu"]


class TestDeduplication:
    def test_longer_root_wins(self):
        matcher = Matcher(
            [make_pattern("siktir", keep_i=True), make_pattern("sikti", keep_i=True)]
        )
        assert rules(matcher, "siktir git") == ["siktir"]

    def test_same_root_reported_once(self):
        matcher = Matcher([make_pattern("orospu")])
        assert rules(matcher, "orospu orospu orospu") == ["orospu"]

    def test_long_multiword_root_hides_short_one(self):
        matcher = Matcher(
            [make_pattern("amına koyayım"), make_pattern("amına", exact=True)]
        )
        assert rules(matcher, "senin amına koyayım") == ["amına koyayım"]

    def test_different_roots_both_reported(self):
        matcher = Matcher([make_pattern("orospu"), make_pattern("yavşak")])
        assert sorted(rules(matcher, "orospu ve yavşak")) == ["orospu", "yavşak"]


class TestMatchMetadata:
    def test_severity_is_carried(self):
        matcher = Matcher([make_pattern("salak", Severity.MILD)])
        found = matches(matcher, "salak herif")
        assert found[0].pattern.severity is Severity.MILD

    def test_source_is_token_for_plain_match(self):
        matcher = Matcher([make_pattern("orospu")])
        assert matches(matcher, "orospu")[0].source == "token"

    @pytest.mark.parametrize("text", ["", "   ", "2-0", "🙂🙂"])
    def test_empty_like_texts_match_nothing(self, text):
        matcher = Matcher([make_pattern("orospu")])
        assert rules(matcher, text) == []
