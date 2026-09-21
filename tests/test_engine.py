"""Karar (verdict) mantigi testleri.

Burada gercek kelime listesi yerine sahte dedektorler kullanilir; boylece
sadece motorun kurallari test edilir.
"""

from __future__ import annotations

import pytest

from xbot.detector.base import FLAG_POSITIVE, FLAG_TARGET, Detector
from xbot.detector.engine import DecisionEngine, DetectionRules
from xbot.models import Level, Match, Severity, Tweet, Verdict


class FakeContentDetector(Detector):
    """Verilen agirlikta tek bir eslesme uretir."""

    name = "fake_content"
    kind = "content"

    def __init__(self, severity: Severity | None, level: Level | None = None) -> None:
        self.severity = severity
        self.level = level

    def analyze(self, tweet, context=None):
        if self.severity is None:
            return Verdict.clean(self.name) if self.level is None else Verdict(
                detector=self.name, level=self.level
            )
        match = Match(
            detector=self.name,
            rule="deneme_kok",
            severity=self.severity,
            matched_text="deneme",
        )
        level = self.level or (
            Level.HIGH if self.severity is Severity.STRONG else Level.SUSPECT
        )
        return Verdict(detector=self.name, level=level, matches=(match,))


class FakeFlagDetector(Detector):
    """Sadece bayrak uretir (hedef isim / olumlu baglam taklidi)."""

    kind = "context"

    def __init__(self, flag: str, name: str = "fake_flag") -> None:
        self.flag = flag
        self.name = name

    def analyze(self, tweet, context=None):
        return Verdict(
            detector=self.name,
            level=Level.CLEAN,
            flags=frozenset({self.flag}),
            reasons=(f"{self.flag} bulundu",),
        )


TWEET = Tweet(tweet_id="1", username="deneme", text="metin")


def build(severity, *, target=False, positive=False, rules=None) -> DecisionEngine:
    detectors: list[Detector] = [FakeContentDetector(severity)]
    if target:
        detectors.append(FakeFlagDetector(FLAG_TARGET, "fake_target"))
    if positive:
        detectors.append(FakeFlagDetector(FLAG_POSITIVE, "fake_positive"))
    return DecisionEngine(detectors, rules or DetectionRules())


class TestBaseRules:
    def test_no_match_is_clean(self):
        decision = build(None).evaluate(TWEET)
        assert decision.level is Level.CLEAN
        assert decision.is_blockable is False
        assert "eşleşmesi bulunamadı" in " ".join(decision.reasons)

    def test_strong_alone_is_high(self):
        decision = build(Severity.STRONG).evaluate(TWEET)
        assert decision.level is Level.HIGH
        assert decision.is_blockable is True

    def test_mild_alone_is_suspect(self):
        assert build(Severity.MILD).evaluate(TWEET).level is Level.SUSPECT

    def test_ambiguous_alone_is_suspect(self):
        assert build(Severity.AMBIGUOUS).evaluate(TWEET).level is Level.SUSPECT

    def test_mild_with_target_is_high(self):
        assert build(Severity.MILD, target=True).evaluate(TWEET).level is Level.HIGH

    def test_ambiguous_with_target_is_high(self):
        decision = build(Severity.AMBIGUOUS, target=True).evaluate(TWEET)
        assert decision.level is Level.HIGH
        assert decision.target_hit is True


class TestConfigurableRules:
    def test_ambiguous_with_target_can_be_suspect(self):
        rules = DetectionRules(ambiguous_with_target="suspect")
        decision = build(Severity.AMBIGUOUS, target=True, rules=rules).evaluate(TWEET)
        assert decision.level is Level.SUSPECT

    def test_mild_with_target_can_be_suspect(self):
        rules = DetectionRules(mild_with_target="suspect")
        decision = build(Severity.MILD, target=True, rules=rules).evaluate(TWEET)
        assert decision.level is Level.SUSPECT

    def test_high_requires_target_downgrades(self):
        rules = DetectionRules(high_requires_target=True)
        decision = build(Severity.STRONG, rules=rules).evaluate(TWEET)
        assert decision.level is Level.SUSPECT
        assert "high_requires_target" in " ".join(decision.reasons)

    def test_high_requires_target_allows_with_target(self):
        rules = DetectionRules(high_requires_target=True)
        decision = build(Severity.STRONG, target=True, rules=rules).evaluate(TWEET)
        assert decision.level is Level.HIGH

    def test_invalid_rule_value_raises(self):
        with pytest.raises(ValueError, match="ambiguous_with_target"):
            DetectionRules(ambiguous_with_target="engelle")


class TestPositiveContextGuard:
    def test_guard_downgrades_ambiguous_with_target(self):
        decision = build(Severity.AMBIGUOUS, target=True, positive=True).evaluate(TWEET)
        assert decision.level is Level.SUSPECT
        assert "Olumlu" in " ".join(decision.reasons)

    def test_guard_downgrades_mild_with_target(self):
        decision = build(Severity.MILD, target=True, positive=True).evaluate(TWEET)
        assert decision.level is Level.SUSPECT

    def test_guard_does_not_save_strong_profanity(self):
        decision = build(Severity.STRONG, target=True, positive=True).evaluate(TWEET)
        assert decision.level is Level.HIGH

    def test_guard_can_be_disabled(self):
        rules = DetectionRules(positive_context_guard=False)
        decision = build(
            Severity.AMBIGUOUS, target=True, positive=True, rules=rules
        ).evaluate(TWEET)
        assert decision.level is Level.HIGH


class TestDecisionContents:
    def test_decision_keeps_evidence(self):
        decision = build(Severity.STRONG, target=True).evaluate(TWEET)
        assert decision.rule_summary == "deneme_kok"
        assert decision.matches[0].detector == "fake_content"
        assert len(decision.verdicts) == 2  # icerik + baglam
        assert decision.tweet is TWEET

    def test_context_matches_are_not_counted_as_content(self):
        decision = build(None, target=True).evaluate(TWEET)
        assert decision.matches == ()
        assert decision.level is Level.CLEAN

    def test_detector_level_without_matches_is_respected(self):
        """Ileride eklenecek yapay zeka dedektoru eslesme olmadan da karar verebilir."""
        engine = DecisionEngine([FakeContentDetector(None, level=Level.HIGH)])
        assert engine.evaluate(TWEET).level is Level.HIGH

    def test_highest_severity_wins_across_detectors(self):
        engine = DecisionEngine(
            [
                FakeContentDetector(Severity.AMBIGUOUS),
                FakeContentDetector(Severity.STRONG),
            ]
        )
        assert engine.evaluate(TWEET).level is Level.HIGH

    def test_describe_is_multiline_turkish(self):
        text = build(Severity.STRONG).evaluate(TWEET).describe()
        assert text.startswith("Karar: YÜKSEK")
