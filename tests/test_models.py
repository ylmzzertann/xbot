"""Veri modelleri testleri."""

from __future__ import annotations

from datetime import datetime, timezone

from xbot.models import DetectionStats, Level, Match, Severity, Tweet, Verdict


class TestTweet:
    def test_username_at_sign_is_stripped(self):
        assert Tweet("1", "@kullanici", "metin").username == "kullanici"

    def test_url_is_built_when_missing(self):
        tweet = Tweet("12345", "kullanici", "metin")
        assert tweet.url == "https://x.com/kullanici/status/12345"
        assert tweet.permalink == tweet.url

    def test_given_url_is_kept(self):
        tweet = Tweet("1", "u", "metin", url="https://x.com/baska/status/9")
        assert tweet.url == "https://x.com/baska/status/9"

    def test_created_at_is_optional(self):
        moment = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        assert Tweet("1", "u", "m", created_at=moment).created_at == moment
        assert Tweet("1", "u", "m").created_at is None


class TestLevelsAndSeverity:
    def test_level_order(self):
        assert Level.CLEAN < Level.SUSPECT < Level.HIGH

    def test_level_labels_are_turkish(self):
        assert Level.CLEAN.label == "TEMİZ"
        assert Level.SUSPECT.label == "ŞÜPHELİ"
        assert Level.HIGH.label == "YÜKSEK"

    def test_severity_order_and_labels(self):
        assert Severity.AMBIGUOUS < Severity.MILD < Severity.STRONG
        assert Severity.STRONG.label == "güçlü"


class TestVerdict:
    def test_clean_helper(self):
        verdict = Verdict.clean("deneme")
        assert verdict.level is Level.CLEAN
        assert verdict.matches == ()
        assert verdict.max_severity is None

    def test_max_severity(self):
        verdict = Verdict(
            detector="d",
            level=Level.SUSPECT,
            matches=(
                Match("d", "a", Severity.AMBIGUOUS, "a"),
                Match("d", "b", Severity.MILD, "b"),
            ),
        )
        assert verdict.max_severity is Severity.MILD


class TestMatchExplanation:
    def test_plain_match(self):
        text = Match("profanity", "siktir", Severity.STRONG, "siktir").explanation
        assert "güçlü" in text and "siktir" in text and "kelime içinde" in text

    def test_obfuscated_match_is_marked(self):
        match = Match("profanity", "siktir", Severity.STRONG, "s*ktir", obfuscated=True)
        assert "gizlenmiş yazım" in match.explanation

    def test_run_source_is_labelled(self):
        match = Match("profanity", "orospu", Severity.STRONG, "orospu", source="run")
        assert "aralıklı yazımda" in match.explanation


class TestDetectionStats:
    def test_counters(self):
        stats = DetectionStats()
        stats.add(Level.CLEAN)
        stats.add(Level.SUSPECT)
        stats.add(Level.HIGH)
        stats.add(Level.HIGH)
        assert (stats.seen, stats.clean, stats.suspect, stats.high) == (4, 1, 1, 2)
