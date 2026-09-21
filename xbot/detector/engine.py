"""Karar motoru: dedektor sonuclarini tek bir karara cevirir.

Kural ozeti (config.yaml -> detection bolumunden ayarlanir):

  guclu kufur                      -> YUKSEK
  hafif hakaret + hedef isim       -> YUKSEK   (mild_with_target: high)
  hafif hakaret, hedef isim yok    -> SUPHELI
  belirsiz ifade + hedef isim      -> YUKSEK   (ambiguous_with_target: high)
  belirsiz ifade, hedef isim yok   -> SUPHELI

Frenler (sadece seviyeyi DUSURUR):
  * olumlu baglam kelimesi varsa (gol, helal, kral...) guclu olmayan
    eslesmeler YUKSEK'e cikarilmaz
  * high_requires_target: true ise hedef isim olmadan YUKSEK verilmez
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..models import Decision, Level, Match, Severity, Tweet, Verdict
from .base import FLAG_POSITIVE, FLAG_TARGET, AnalysisContext, Detector

#: detection.*_with_target ayarlari icin gecerli degerler
TARGET_ACTIONS = ("high", "suspect")


@dataclass(frozen=True, slots=True)
class DetectionRules:
    """Karar kurallari (config.yaml -> detection)."""

    high_requires_target: bool = False
    ambiguous_with_target: str = "high"
    mild_with_target: str = "high"
    positive_context_guard: bool = True

    def __post_init__(self) -> None:
        for field_name in ("ambiguous_with_target", "mild_with_target"):
            value = getattr(self, field_name)
            if value not in TARGET_ACTIONS:
                raise ValueError(
                    f"detection.{field_name} sadece "
                    f"{' veya '.join(TARGET_ACTIONS)} olabilir (verilen: {value!r})"
                )


class DecisionEngine:
    """Dedektorleri sirayla calistirir ve nihai karari uretir."""

    def __init__(
        self,
        detectors: Sequence[Detector],
        rules: DetectionRules | None = None,
    ) -> None:
        self.detectors = list(detectors)
        self.rules = rules or DetectionRules()

    # --- kurulum ---

    @classmethod
    def from_config(cls, config) -> "DecisionEngine":
        """config.yaml'dan okunmus ayarlarla motoru kurar."""
        from .context import PositiveContextDetector
        from .profanity import ProfanityDetector
        from .target import TargetDetector

        detection = config.detection
        detectors: list[Detector] = [
            ProfanityDetector.from_files(
                config.files.profanity,
                config.files.allowlist_words,
                config.files.allowlist_phrases,
                min_glue_length=detection.min_root_length_for_glue,
            ),
            TargetDetector(config.target_names),
        ]
        if detection.positive_context_guard:
            detectors.append(
                PositiveContextDetector.from_file(config.files.positive_context)
            )
        rules = DetectionRules(
            high_requires_target=detection.high_requires_target,
            ambiguous_with_target=detection.ambiguous_with_target,
            mild_with_target=detection.mild_with_target,
            positive_context_guard=detection.positive_context_guard,
        )
        return cls(detectors, rules)

    # --- degerlendirme ---

    def evaluate(self, tweet: Tweet) -> Decision:
        """Tweeti tum dedektorlerden gecirip karar uretir."""
        ctx = AnalysisContext(tweet=tweet)
        verdicts: list[Verdict] = []
        content_verdicts: list[Verdict] = []
        flags: set[str] = set()
        reasons: list[str] = []

        for detector in self.detectors:
            verdict = detector.analyze(tweet, ctx)
            verdicts.append(verdict)
            flags.update(verdict.flags)
            reasons.extend(verdict.reasons)
            if detector.kind == "content":
                content_verdicts.append(verdict)

        content_matches: tuple[Match, ...] = tuple(
            match for verdict in content_verdicts for match in verdict.matches
        )
        base_level = max(
            (verdict.level for verdict in content_verdicts), default=Level.CLEAN
        )
        severity = max((m.severity for m in content_matches), default=None)
        target_hit = FLAG_TARGET in flags
        positive = FLAG_POSITIVE in flags

        level = base_level
        if severity is not None:
            level = max(level, self._level_for(severity, target_hit, reasons))

        level = self._apply_guards(level, severity, target_hit, positive, reasons)

        if level is Level.CLEAN and not content_matches:
            reasons.append("Küfür/hakaret eşleşmesi bulunamadı.")

        return Decision(
            tweet=tweet,
            level=level,
            matches=content_matches,
            reasons=tuple(reasons),
            flags=frozenset(flags),
            verdicts=tuple(verdicts),
        )

    # --- ic kurallar ---

    def _level_for(
        self, severity: Severity, target_hit: bool, reasons: list[str]
    ) -> Level:
        if severity is Severity.STRONG:
            reasons.append("Açık küfür/hakaret tespit edildi → YÜKSEK.")
            return Level.HIGH

        kind, setting = (
            ("Hafif hakaret", self.rules.mild_with_target)
            if severity is Severity.MILD
            else ("Belirsiz ifade", self.rules.ambiguous_with_target)
        )
        if target_hit and setting == "high":
            reasons.append(f"{kind} + hedef isim aynı tweette → YÜKSEK.")
            return Level.HIGH
        if target_hit:
            reasons.append(
                f"{kind} + hedef isim var ama ayar 'suspect' → ŞÜPHELİ."
            )
        else:
            reasons.append(f"{kind}, hedef isim yok → ŞÜPHELİ.")
        return Level.SUSPECT

    def _apply_guards(
        self,
        level: Level,
        severity: Severity | None,
        target_hit: bool,
        positive: bool,
        reasons: list[str],
    ) -> Level:
        if (
            level is Level.HIGH
            and self.rules.positive_context_guard
            and positive
            and severity is not None
            and severity is not Severity.STRONG
        ):
            reasons.append(
                "Olumlu/sevinç bağlamı bulundu → güvenlik için YÜKSEK yerine ŞÜPHELİ."
            )
            level = Level.SUSPECT
        if level is Level.HIGH and self.rules.high_requires_target and not target_hit:
            reasons.append(
                "Ayar gereği (high_requires_target) hedef isim olmadan YÜKSEK "
                "verilmiyor → ŞÜPHELİ."
            )
            level = Level.SUSPECT
        return level
