"""Kullanicinin o an yazdigi kelime/cumleyi arayan dedektor.

"phrase" komutunda kullanilir: kullanici her calistirmada farkli bir ifade
yazar, program o ifadeyi iceren tweetleri bulur. Kufur listesinden
bagimsizdir; ayni Turkce normalizasyon kullanilir, yani

    "Okan istifa"  ->  "OKAN İSTİFA", "okan istifaaa", "#OkanIstifa",
                       "o.k.a.n istifa"  hepsi eslesir.

Tek kelimelik ifadeler varsayilan olarak kelime ICINDE de aranir ("salak" ->
"salaklar"). Sadece tam kelime istenirse whole_word=True verilir.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..models import Level, Match, Severity, Tweet, Verdict
from .base import AnalysisContext, Detector, register_detector
from .matcher import Matcher, make_pattern
from .normalizer import normalize_pattern

#: Normalize edildikten sonra en az bu kadar harf olmali
MIN_PHRASE_LETTERS = 2

#: Bundan kisa ifadeler cok fazla tweet yakalayabilir: kullanici uyarilir
SHORT_PHRASE_LETTERS = 4


def phrase_letters(phrase: str) -> int:
    """Ifadenin normalize edilmis harf sayisi."""
    return len(normalize_pattern(phrase).folded)


def validate_phrase(phrase: str) -> str:
    """Ifadeyi temizler ve dogrular; gecersizse Turkce ValueError yukseltir."""
    cleaned = " ".join((phrase or "").split())
    if not cleaned:
        raise ValueError("Bir kelime ya da cümle yazmalısın.")
    if phrase_letters(cleaned) < MIN_PHRASE_LETTERS:
        raise ValueError(
            f"'{cleaned}' çok kısa: en az {MIN_PHRASE_LETTERS} harf olmalı."
        )
    return cleaned


def is_short_phrase(phrase: str) -> bool:
    return phrase_letters(phrase) < SHORT_PHRASE_LETTERS


def rule_label(phrase: str) -> str:
    """Kayitlarda gorunecek kural adi: ifade: "okan istifa" """
    return f'ifade: "{phrase}"'


@register_detector("phrase")
class PhraseDetector(Detector):
    """Verilen ifadeleri arar; bulursa YUKSEK karar verir."""

    name = "phrase"
    kind = "content"

    def __init__(self, phrases: Sequence[str], *, whole_word: bool = False) -> None:
        self.phrases = [" ".join(p.split()) for p in phrases if p and p.strip()]
        self.whole_word = whole_word
        patterns = []
        for phrase in self.phrases:
            multiword = len(phrase.split()) > 1
            patterns.append(
                make_pattern(
                    phrase,
                    Severity.STRONG,
                    # cok kelimeli ifadelerde "tam kelime" bayragi kullanilamaz
                    exact=whole_word and not multiword,
                )
            )
        # Kullanici ifadesi icin masum kelime listesi uygulanmaz
        self.matcher = Matcher(patterns, [], min_glue_length=1)

    def matches(self, tweet: Tweet) -> bool:
        return self.analyze(tweet).level is Level.HIGH

    def analyze(self, tweet: Tweet, context: AnalysisContext | None = None) -> Verdict:
        if not self.phrases:
            return Verdict.clean(self.name)
        ctx = self.context_for(tweet, context)
        raw_matches = self.matcher.find(ctx.normalized)
        if not raw_matches:
            return Verdict.clean(self.name)
        matches = tuple(
            Match(
                detector=self.name,
                rule=rule_label(raw.pattern.raw),
                severity=Severity.STRONG,
                matched_text=raw.matched_text,
                source=raw.source,
                obfuscated=raw.obfuscated,
                note="aranan ifade",
            )
            for raw in raw_matches
        )
        found = ", ".join(f'"{raw.pattern.raw}"' for raw in raw_matches)
        return Verdict(
            detector=self.name,
            level=Level.HIGH,
            matches=matches,
            reasons=(f"Aranan ifade bulundu: {found}",),
        )
