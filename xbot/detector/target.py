"""Hedef isim dedektoru (baglam dedektoru).

config.yaml -> target_names listesindeki isimlerden biri tweette geciyorsa
FLAG_TARGET bayragini kaldirir. Karar seviyesi uretmez; motor bu bayragi
kufur agirligiyla birlestirir.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..models import Level, Match, Severity, Tweet, Verdict
from .base import FLAG_TARGET, AnalysisContext, Detector, register_detector
from .matcher import Matcher, make_pattern


@register_detector("target")
class TargetDetector(Detector):
    """Hedef isimleri (ornegin "okan", "buruk") arar."""

    name = "target"
    kind = "context"

    def __init__(self, names: Sequence[str]) -> None:
        self.names = [n.strip() for n in names if n and n.strip()]
        patterns = [
            make_pattern(name, Severity.AMBIGUOUS) for name in self.names
        ]
        # Isimler icin istisna listesi kullanilmaz.
        self.matcher = Matcher(patterns, [], min_glue_length=5)

    def analyze(self, tweet: Tweet, context: AnalysisContext | None = None) -> Verdict:
        if not self.names:
            return Verdict.clean(self.name)
        ctx = self.context_for(tweet, context)
        raw_matches = self.matcher.find(ctx.normalized)
        if not raw_matches:
            return Verdict.clean(self.name)
        matches = tuple(
            Match(
                detector=self.name,
                rule=raw.pattern.raw,
                severity=Severity.AMBIGUOUS,
                matched_text=raw.matched_text,
                source=raw.source,
                obfuscated=raw.obfuscated,
                note="hedef isim",
            )
            for raw in raw_matches
        )
        names = ", ".join(dict.fromkeys(m.rule for m in matches))
        return Verdict(
            detector=self.name,
            level=Level.CLEAN,
            matches=matches,
            reasons=(f"Hedef isim eşleşti: {names}",),
            flags=frozenset({FLAG_TARGET}),
        )
