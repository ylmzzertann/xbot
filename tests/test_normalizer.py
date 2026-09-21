"""Metin normalizasyonu testleri."""

from __future__ import annotations

import pytest

from xbot.detector.normalizer import (
    WILDCARD,
    collapse_repeats,
    fold_i,
    normalize_pattern,
    normalize_text,
    split_tokens,
)


class TestTurkishCase:
    def test_dotted_capital_i_becomes_i(self):
        # "İ" -> "i": Turkce kurali
        assert normalize_text("SİKTİR").glued.plain == "siktir"

    def test_dotless_capital_i_becomes_dotless(self):
        # "I" -> noktasiz i: bu yuzden listede "sıktır" da ayri kok olarak var
        assert normalize_text("SIKTIR").glued.plain == "sıktır"

    def test_turkish_letters_are_simplified(self):
        assert normalize_text("YAVŞAK ÇÖPLÜĞÜ").glued.plain == "yavsakcoplugu"

    def test_dotless_i_is_preserved_in_plain_but_folded_in_folded(self):
        form = normalize_text("sıkıntı").glued
        assert form.plain == "sıkıntı"
        assert form.folded == "sikinti"


class TestCollapseAndLeet:
    def test_repeated_letters_collapse(self):
        assert normalize_text("amkkkkk").glued.plain == "amk"
        assert collapse_repeats("aaabbbccc") == "abc"
        assert collapse_repeats("") == ""

    def test_digits_replace_letters_when_word_has_letters(self):
        assert normalize_text("s1kt1r").glued.plain == "siktir"
        assert normalize_text("$erefsiz").glued.plain == "serefsiz"
        assert normalize_text("am@na").glued.plain == "amana"

    def test_pure_number_tokens_are_dropped(self):
        # skorlar bozulmasin: "2-0" harf uretmez
        assert normalize_text("2-0 kazandık").glued.plain == "kazandık"

    def test_fold_i_helper(self):
        assert fold_i("sık") == "sik"


class TestSeparatorsAndMasks:
    def test_separators_are_removed_in_plain_form(self):
        assert normalize_text("a.m.k").glued.plain == "amk"
        assert normalize_text("s_i_k").glued.plain == "sik"

    def test_separators_become_wildcards_in_masked_form(self):
        form = normalize_text("a.m.k").glued
        assert form.plain_masked == f"a{WILDCARD}m{WILDCARD}k"
        assert form.has_mask is True

    def test_mask_only_between_letters(self):
        form = normalize_text("...siktir...").glued
        assert form.plain_masked == "siktir"

    def test_consecutive_masks_collapse(self):
        form = normalize_text("s**k").glued
        assert form.plain_masked == f"s{WILDCARD}k"

    def test_emoji_breaks_masking_but_is_dropped(self):
        form = normalize_text("gol\U0001f600gol").glued
        assert form.plain == "golgol"
        assert form.has_mask is False

    def test_invisible_characters_are_ignored(self):
        assert normalize_text("si​ktir").glued.plain == "siktir"


class TestTokensAndRuns:
    def test_mentions_and_hashtags_lose_their_marker(self):
        norm = normalize_text("@OkanBuruk #Galatasaray")
        assert [t.form.plain for t in norm.tokens] == ["okanburuk", "galatasaray"]

    def test_spaced_out_letters_form_a_run(self):
        norm = normalize_text("s i k t i r")
        assert [r.plain for r in norm.runs] == ["siktir"]

    def test_long_words_do_not_join_runs(self):
        norm = normalize_text("klasik bir maç")
        assert norm.runs == ()

    def test_single_short_token_is_not_a_run(self):
        norm = normalize_text("bu maçta")
        assert norm.runs == ()

    def test_run_breaks_on_long_token(self):
        norm = normalize_text("a m klasik k a")
        assert [r.plain for r in norm.runs] == ["am", "ka"]

    def test_glued_form_joins_everything(self):
        norm = normalize_text("amına koyayım")
        assert norm.glued.folded == "aminakoyayim"

    def test_empty_text(self):
        norm = normalize_text("   ")
        assert norm.tokens == ()
        assert norm.is_empty is True


class TestSplitAndPattern:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("bir, iki; üç", ["bir", "iki", "üç"]),
            ("(parantez)", ["parantez"]),
            ('"alıntı"', ["alıntı"]),
            ("satır\nsonu", ["satır", "sonu"]),
            ("a.m.k", ["a.m.k"]),  # nokta bolmez: gizleme olabilir
        ],
    )
    def test_split_tokens(self, text, expected):
        assert split_tokens(text) == expected

    def test_normalize_pattern_removes_spaces(self):
        form = normalize_pattern("göt oğlanı")
        assert form.folded == "gotoglani"

    def test_normalize_pattern_has_no_wildcards_for_spaces(self):
        form = normalize_pattern("amına koyayım")
        assert WILDCARD not in form.plain_masked
