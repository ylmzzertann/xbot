"""Kelime listesi tabanli kufur/hakaret dedektoru."""

from __future__ import annotations

from pathlib import Path

from ..models import Level, Match, Severity, Tweet, Verdict
from .base import AnalysisContext, Detector, register_detector
from .matcher import Matcher, Pattern


@register_detector("profanity")
class ProfanityDetector(Detector):
    """data/profanity.txt listesine gore kufur arar.

    Karar seviyesi sadece eslesmenin agirligina bakar:
      * guclu (strong)  -> YUKSEK
      * hafif (mild)    -> SUPHELI
      * belirsiz        -> SUPHELI
    Hedef isim / olumlu baglam gibi baglam kurallarini motor (engine.py) uygular.
    """

    name = "profanity"
    kind = "content"

    def __init__(self, matcher: Matcher, *, name: str | None = None) -> None:
        self.matcher = matcher
        if name:
            self.name = name

    @classmethod
    def from_files(
        cls,
        profanity_path: str | Path,
        allowlist_path: str | Path | None = None,
        phrases_path: str | Path | None = None,
        *,
        min_glue_length: int = 6,
        name: str | None = None,
    ) -> "ProfanityDetector":
        """Kufur ve istisna listelerini dosyadan yukleyerek dedektor olusturur."""
        from ..wordlists import load_profanity_patterns, load_word_list

        patterns: list[Pattern] = load_profanity_patterns(profanity_path)
        allow_words = load_word_list(allowlist_path) if allowlist_path else ()
        phrases = load_word_list(phrases_path) if phrases_path else ()
        matcher = Matcher(
            patterns,
            list(allow_words),
            allow_phrases=list(phrases),
            min_glue_length=min_glue_length,
        )
        return cls(matcher, name=name)

    def analyze(self, tweet: Tweet, context: AnalysisContext | None = None) -> Verdict:
        ctx = self.context_for(tweet, context)
        raw_matches = self.matcher.find(ctx.normalized)
        if not raw_matches:
            return Verdict.clean(self.name)

        matches = tuple(
            Match(
                detector=self.name,
                rule=raw.pattern.raw,
                severity=raw.pattern.severity,
                matched_text=raw.matched_text,
                source=raw.source,
                obfuscated=raw.obfuscated,
            )
            for raw in raw_matches
        )
        max_severity = max(m.severity for m in matches)
        level = Level.HIGH if max_severity is Severity.STRONG else Level.SUSPECT
        reasons = tuple(m.explanation for m in matches)
        return Verdict(
            detector=self.name, level=level, matches=matches, reasons=reasons
        )
