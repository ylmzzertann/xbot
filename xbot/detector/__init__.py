"""Dedektor paketi.

Dedektorler "plugin" mantigiyla ayrilmistir: yeni bir dedektor (ornegin yapay
zeka tabanli siniflandirici) eklemek icin base.Detector arayuzunu uygulamak ve
register_detector ile kayda eklemek yeterlidir.
"""

from .base import (
    FLAG_POSITIVE,
    FLAG_TARGET,
    AnalysisContext,
    Detector,
    build_detector,
    register_detector,
)
from .context import PositiveContextDetector
from .engine import DecisionEngine, DetectionRules
from .matcher import Matcher, Pattern, make_pattern
from .normalizer import Form, NormalizedText, normalize_pattern, normalize_text
from .profanity import ProfanityDetector
from .target import TargetDetector

__all__ = [
    "FLAG_POSITIVE",
    "FLAG_TARGET",
    "AnalysisContext",
    "DecisionEngine",
    "DetectionRules",
    "Detector",
    "Form",
    "Matcher",
    "NormalizedText",
    "Pattern",
    "PositiveContextDetector",
    "ProfanityDetector",
    "TargetDetector",
    "build_detector",
    "make_pattern",
    "normalize_pattern",
    "normalize_text",
    "register_detector",
]
