"""Olumlu baglam dedektoru (baglam dedektoru).

"amk gol geldi" gibi sevinc ifadelerini ayirt etmeye yardim eder. Tweette
data/positive_context.txt listesinden bir kelime varsa FLAG_POSITIVE bayragi
kaldirilir; motor bu durumda BELIRSIZ/HAFIF eslesmeleri YUKSEK'e cikarmaz.

Bu dedektor yalnizca engellemeyi AZALTIR, asla artirmaz.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..models import Level, Match, Severity, Tweet, Verdict
from .base import FLAG_POSITIVE, AnalysisContext, Detector, register_detector
from .matcher import Matcher, make_pattern


@register_detector("positive_context")
class PositiveContextDetector(Detector):
    """Sevinc/olumlu baglam kelimelerini arar."""

    name = "positive_context"
    kind = "context"

    def __init__(self, words: Sequence[str]) -> None:
        self.words = [w.strip() for w in words if w and w.strip()]
        patterns = [make_pattern(w, Severity.AMBIGUOUS) for w in self.words]
        self.matcher = Matcher(patterns, [], min_glue_length=99)

    @classmethod
    def from_file(cls, path: str | Path) -> "PositiveContextDetector":
        from ..wordlists import load_word_list

        return cls(load_word_list(path))

    def analyze(self, tweet: Tweet, context: AnalysisContext | None = None) -> Verdict:
        if not self.words:
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
                note="olumlu bağlam",
            )
            for raw in raw_matches
        )
        words = ", ".join(dict.fromkeys(m.rule for m in matches))
        return Verdict(
            detector=self.name,
            level=Level.CLEAN,
            matches=matches,
            reasons=(f"Olumlu bağlam kelimesi: {words}",),
            flags=frozenset({FLAG_POSITIVE}),
        )
