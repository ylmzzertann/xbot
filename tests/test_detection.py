"""Uctan uca tespit testleri: gercek kelime listeleri + gercek motor.

En onemli bolum TestFalsePositives: masum cumleler ASLA engellenmemeli.
"""

from __future__ import annotations

import pytest

from xbot.detector.base import FLAG_POSITIVE, FLAG_TARGET
from xbot.detector.context import PositiveContextDetector
from xbot.detector.profanity import ProfanityDetector
from xbot.detector.target import TargetDetector
from xbot.models import Level, Severity, Tweet
from xbot.wordlists import WordListError

# --------------------------------------------------------------------------
# Yakalanmasi gerekenler
# --------------------------------------------------------------------------

STRONG_PROFANITY = [
    "siktir git buradan",
    "SİKTİR GİT",
    "SIKTIR GIT",
    "orospu çocuğu",
    "amına koyayım",
    "aminakoyim",
    "yavşak herif",
    "şerefsiz adam",
    "göt herif",
    "ibne",
    "puşt",
    "kaltak",
    "pezevenk",
    "sikeyim böyle işi",
    "piç",
    "namussuz",
]

OBFUSCATED_PROFANITY = [
    "s1kt1r git",
    "s*ktir",
    "sikttttir",
    "s i k t i r",
    "o r o s p u",
    "$erefsiz",
    "amınak0yayım",
    "or*spu",
    "si̇ktir",
]

AMBIGUOUS_TEXTS = [
    "amk",
    "amk gol",
    "amkkkk ne gol",
    "a.m.k",
    "aq",
    "mk",
    "salak",
    "geri zekalı hoca",
    "aptal gibi oynadık",
    "hayvan",
]

# --------------------------------------------------------------------------
# Yanlis pozitif korpusu: hepsi TEMIZ cikmali
# --------------------------------------------------------------------------

CLEAN_CORPUS = [
    # kufur kokunu iceren masum kelimeler
    "sıkıntı yok kardeşim",
    "sikinti yok kardesim",
    "sık sık maça gidiyorum",
    "çok sıkıldım bu maçta",
    "klasik bir Galatasaray maçı",
    "psikolojik üstünlük bizde",
    "psikiyatri uzmanı açıkladı",
    "aşık oldum bu takıma",
    "ışıklar kapandı, maç durdu",
    "müzik açık, keyif yapıyoruz",
    "fizik tedavi görüyor",
    "seni maça götürdüm",
    "beni de götürün lütfen",
    "kupayı müzeye götürecekler",
    "gotik mimari gibi bir stat",
    "adamına göre oynamak lazım",
    "damına kadar doldu",
    "takımına güvenen tek kişi",
    "laminat parke döşendi",
    "ampul patladı",
    "amatör küme maçı",
    "amacımız şampiyonluk",
    "ama bu kadar da olmaz",
    "yapıcı eleştiri yapıyorum",
    "kapıcı geldi",
    "boks maçı gibiydi",
    "malzeme sıkıntısı var",
    "maliyet çok arttı",
    "Malatya deplasmanı zor",
    "İtalya'da oynadı bir dönem",
    "itibarını korumalı",
    "itiraf ediyorum, çok iyiydi",
    "müsait değilim şu an",
    # cok kelimeli masum kaliplar
    "eşek arısı soktu",
    "eşek şakası yapmışlar",
    "kaşar peyniri aldım",
    "alçak basınç geliyor",
    "domuz gribi vakası",
    "maymun iştahlı olmayalım",
    "mal sahibi konuştu",
    "hayvan gibi oynadı maşallah",
    "köpek balığı gibi hızlı",
    "hayvan hakları önemli",
    # normal futbol yorumlari
    "Okan Buruk bugün çok iyi bir taktik kurdu",
    "Okan Buruk'a güveniyorum",
    "2-0 kazandık, harika",
    "bu takım çok kötü oynadı",
    "hakem kararları tartışılır",
    "transfer haberleri çıktı",
    "Okan Buruk kral adam",
    "maç 90+5'te bitti",
]

# Belirsiz kelime iceren, engellenmemesi gereken (ama rapora giren) ornekler
SUSPECT_BUT_NOT_BLOCKED = [
    "manyak bir gol attı",
    "maçın ayı belli değil",
    "psikopat gibi savundu",
]


class TestStrongProfanity:
    @pytest.mark.parametrize("text", STRONG_PROFANITY)
    def test_strong_profanity_is_high(self, decide, text):
        decision = decide(text)
        assert decision.level is Level.HIGH, decision.reasons
        assert decision.is_blockable is True
        assert decision.rule_summary

    @pytest.mark.parametrize("text", OBFUSCATED_PROFANITY)
    def test_obfuscated_profanity_is_high(self, decide, text):
        decision = decide(text)
        assert decision.level is Level.HIGH, decision.reasons


class TestAmbiguous:
    @pytest.mark.parametrize("text", AMBIGUOUS_TEXTS)
    def test_ambiguous_is_suspect_not_blocked(self, decide, text):
        decision = decide(text)
        assert decision.level is Level.SUSPECT, decision.reasons
        assert decision.is_blockable is False

    def test_celebration_with_target_is_not_blocked(self, decide):
        # "amk" + hedef isim normalde YUKSEK olurdu; sevinc kelimeleri freni devreye girer
        decision = decide("okan buruk amk kral adam ya")
        assert decision.level is Level.SUSPECT
        assert FLAG_POSITIVE in decision.flags
        assert FLAG_TARGET in decision.flags

    def test_ambiguous_with_target_is_high(self, decide):
        decision = decide("okan buruk amk")
        assert decision.level is Level.HIGH
        assert decision.target_hit is True

    def test_mild_with_target_is_high(self, decide):
        decision = decide("Okan Buruk salak")
        assert decision.level is Level.HIGH

    def test_mild_without_target_is_suspect(self, decide):
        assert decide("hoca salak").level is Level.SUSPECT


class TestFalsePositives:
    @pytest.mark.parametrize("text", CLEAN_CORPUS)
    def test_innocent_text_is_clean(self, decide, text):
        decision = decide(text)
        assert decision.level is Level.CLEAN, (
            f"{text!r} temiz olmalıydı → {decision.rule_summary} / {decision.reasons}"
        )

    @pytest.mark.parametrize("text", SUSPECT_BUT_NOT_BLOCKED)
    def test_context_dependent_words_are_never_blocked(self, decide, text):
        decision = decide(text)
        assert decision.is_blockable is False, decision.reasons

    def test_strong_profanity_inside_innocent_sentence_still_caught(self, decide):
        # istisna listesi kufuru gizlemesin
        decision = decide("sıkıntı yok ama sen siktir git")
        assert decision.level is Level.HIGH


class TestProfanityDetectorUnit:
    @pytest.fixture
    def detector(self, data_dir) -> ProfanityDetector:
        return ProfanityDetector.from_files(
            data_dir / "profanity.txt",
            data_dir / "allowlist_words.txt",
            data_dir / "allowlist_phrases.txt",
        )

    def test_verdict_fields(self, detector):
        verdict = detector.analyze(Tweet("1", "user", "siktir git"))
        assert verdict.detector == "profanity"
        assert verdict.level is Level.HIGH
        assert verdict.max_severity is Severity.STRONG
        assert verdict.matches[0].rule == "siktir"
        assert verdict.reasons

    def test_clean_verdict_has_no_matches(self, detector):
        verdict = detector.analyze(Tweet("1", "user", "harika bir maçtı"))
        assert verdict.level is Level.CLEAN
        assert verdict.matches == ()

    def test_evidence_is_enough_to_undo(self, detector):
        """Yanlis engellemeyi geri almak icin kanit yeterli olmali."""
        tweet = Tweet("12345", "kotu_hesap", "orospu çocuğu")
        verdict = detector.analyze(tweet)
        match = verdict.matches[0]
        assert match.rule == "orospu"
        assert match.matched_text
        assert match.explanation
        assert tweet.permalink == "https://x.com/kotu_hesap/status/12345"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(WordListError):
            ProfanityDetector.from_files(tmp_path / "yok.txt")

    def test_detector_kind(self, detector):
        assert detector.kind == "content"


class TestTargetDetector:
    def test_flag_is_raised(self):
        detector = TargetDetector(["okan", "buruk"])
        verdict = detector.analyze(Tweet("1", "u", "Okan Buruk açıklama yaptı"))
        assert FLAG_TARGET in verdict.flags
        assert verdict.level is Level.CLEAN  # tek basina karar uretmez

    def test_no_flag_without_name(self):
        detector = TargetDetector(["okan"])
        assert detector.analyze(Tweet("1", "u", "Fenerbahçe maçı")).flags == frozenset()

    def test_empty_name_list_is_harmless(self):
        detector = TargetDetector([])
        assert detector.analyze(Tweet("1", "u", "okan buruk")).flags == frozenset()

    def test_name_in_mention_is_found(self):
        detector = TargetDetector(["okan buruk"])
        verdict = detector.analyze(Tweet("1", "u", "@OkanBuruk neredesin"))
        assert FLAG_TARGET in verdict.flags


class TestPositiveContextDetector:
    def test_flag_is_raised(self, data_dir):
        detector = PositiveContextDetector.from_file(data_dir / "positive_context.txt")
        verdict = detector.analyze(Tweet("1", "u", "ne gol ya helal"))
        assert FLAG_POSITIVE in verdict.flags

    def test_no_flag_for_neutral_text(self, data_dir):
        detector = PositiveContextDetector.from_file(data_dir / "positive_context.txt")
        assert detector.analyze(Tweet("1", "u", "maç bitti")).flags == frozenset()

    def test_detector_kind_is_context(self, data_dir):
        detector = PositiveContextDetector.from_file(data_dir / "positive_context.txt")
        assert detector.kind == "context"
