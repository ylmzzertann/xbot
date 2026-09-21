"""Kok eslestirme motoru.

Kelime listesindeki kokleri normalize edilmis metin uzerinde arar. Uc ayri
gecis yapilir:

1. kelime gecisi ("token") : her kelimenin kendi icinde arama  -> en guvenilir
2. birlesik gecis ("glue")  : tum kelimeler bitisik ("aminakoyayim")
3. aralikli gecis ("run")   : "s i k t i r" gibi harf harf yazimlar

Her eslesme, masum kelime istisna listesine ("allowlist") karsi kontrol edilir:
kok, masum bir kelimenin ICINDE kaliyorsa eslesme sayilmaz. Ornek: "gotur"
kelimesi "got" kokunu kapsar, bu yuzden "seni maca goturdum" temizdir.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Severity
from .normalizer import WILDCARD, Form, NormalizedText, normalize_pattern

#: Kok listesinde kullanilabilecek bayraklar
KNOWN_FLAGS = frozenset({"strong", "mild", "ambiguous", "exact", "keep_i"})


@dataclass(frozen=True, slots=True)
class Pattern:
    """Listeden okunmus tek bir kok."""

    raw: str  # listede yazdigi hali (raporlarda gosterilir)
    severity: Severity
    form: Form
    exact: bool = False  # sadece tam kelime olarak eslesir
    keep_i: bool = False  # noktasiz i / i ayrimi korunur
    multiword: bool = False  # listede bosluk iceriyordu ("got oglani")

    @property
    def key(self) -> str:
        """Karsilastirmada kullanilacak kalip."""
        return self.form.plain if self.keep_i else self.form.folded

    @property
    def length(self) -> int:
        return len(self.key)


@dataclass(frozen=True, slots=True)
class RawMatch:
    """Eslestirme motorunun ham cikti birimi."""

    pattern: Pattern
    matched_text: str
    source: str  # token | glue | run
    obfuscated: bool


def make_pattern(
    raw: str,
    severity: Severity = Severity.STRONG,
    *,
    exact: bool = False,
    keep_i: bool = False,
) -> Pattern:
    """Metinden bir Pattern uretir."""
    return Pattern(
        raw=raw.strip(),
        severity=severity,
        form=normalize_pattern(raw),
        exact=exact,
        multiword=len(raw.split()) > 1,
        keep_i=keep_i,
    )


def _find_literal(hay: str, pattern: Pattern) -> tuple[int, int] | None:
    """Duz (jokersiz) arama."""
    key = pattern.key
    if not key or not hay:
        return None
    if pattern.exact:
        return (0, len(hay)) if hay == key else None
    index = hay.find(key)
    if index < 0:
        return None
    return (index, index + len(key))


def _max_wildcards(length: int) -> int:
    """Kalip uzunluguna gore izin verilen en fazla joker sayisi."""
    return max(1, length // 4)


def _find_wildcard(hay: str, pattern: Pattern) -> tuple[int, int] | None:
    """Joker (maske) iceren arama: "s*ktir" -> "siktir".

    hay icindeki WILDCARD karakteri herhangi bir harf yerine gecer. Cok fazla
    jokerle eslesmeyi onlemek icin ust sinir uygulanir.
    """
    key = pattern.key
    if len(key) < 3 or WILDCARD not in hay:
        return None
    limit = _max_wildcards(len(key))
    hay_len = len(hay)
    key_len = len(key)
    for start in range(0, hay_len - key_len + 1):
        used = 0
        ok = True
        for offset in range(key_len):
            char = hay[start + offset]
            if char == key[offset]:
                continue
            if char == WILDCARD:
                used += 1
                if used > limit:
                    ok = False
                    break
                continue
            ok = False
            break
        if ok and used:
            end = start + key_len
            if pattern.exact and not (start == 0 and end == hay_len):
                continue
            return (start, end)
    return None


def _covering_allow_word(
    hay: str, start: int, end: int, allow_words: tuple[str, ...]
) -> str | None:
    """Eslesmeyi kapsayan masum kelime varsa onu dondurur."""
    for word in allow_words:
        if not word:
            continue
        index = hay.find(word)
        while index >= 0:
            if index <= start and index + len(word) >= end:
                return word
            index = hay.find(word, index + 1)
    return None


class Matcher:
    """Kok listesini normalize edilmis metin uzerinde arar."""

    def __init__(
        self,
        patterns: list[Pattern],
        allow_words: list[str] | tuple[str, ...] = (),
        *,
        allow_phrases: list[str] | tuple[str, ...] = (),
        min_glue_length: int = 6,
    ) -> None:
        # Uzun kokler once denenir: "siktir" eslesirse "sikti" ayrica
        # raporlanmasin (ayni kok ailesi icin tek kanit yeter).
        self.patterns = sorted(patterns, key=lambda p: -p.length)
        self.min_glue_length = min_glue_length
        allow_forms = [normalize_pattern(w) for w in allow_words]
        self._allow_plain = tuple(f.plain for f in allow_forms if f.plain)
        self._allow_folded = tuple(f.folded for f in allow_forms if f.folded)
        phrase_forms = [normalize_pattern(p) for p in allow_phrases]
        self._phrase_plain = tuple(f.plain for f in phrase_forms if f.plain)
        self._phrase_folded = tuple(f.folded for f in phrase_forms if f.folded)

    # --- yardimcilar ---

    def _allow_words(self, pattern: Pattern) -> tuple[str, ...]:
        return self._allow_plain if pattern.keep_i else self._allow_folded

    def _phrase_suppressed(self, norm: NormalizedText) -> set[str]:
        """Masum kalip icinde kalan kokleri bu metin icin devre disi birakir.

        Ornek: "esek arisi" kalibi metinde varsa "esek" koku aranmaz.
        """
        if not self._phrase_plain:
            return set()
        suppressed: set[str] = set()
        for pattern in self.patterns:
            folded = not pattern.keep_i
            phrases = self._phrase_folded if folded else self._phrase_plain
            hay = norm.glued.get(folded=folded, masked=False)
            key = pattern.key
            if not key:
                continue
            for phrase in phrases:
                if key in phrase and phrase in hay:
                    suppressed.add(pattern.raw)
                    break
        return suppressed

    def _accept(
        self, hay: str, span: tuple[int, int] | None, pattern: Pattern
    ) -> str | None:
        """Eslesme gecerliyse bulunan metni dondurur, degilse None."""
        if span is None:
            return None
        start, end = span
        if _covering_allow_word(hay, start, end, self._allow_words(pattern)):
            return None
        return hay[start:end].replace(WILDCARD, "*")

    # --- ana arama ---

    @staticmethod
    def _drop_redundant(results: list[RawMatch]) -> list[RawMatch]:
        """Uzun bir kok zaten eslestiyse onun icinde kalan kisa kokleri atar.

        Ornek: "amina koyayim" eslestiyse ayrica "amina" raporlanmaz.
        """
        keys = [r.pattern.key for r in results]
        kept: list[RawMatch] = []
        for index, result in enumerate(results):
            key = result.pattern.key
            covered = any(
                other_index != index and len(other) > len(key) and key in other
                for other_index, other in enumerate(keys)
            )
            if not covered:
                kept.append(result)
        return kept

    def _redundant(self, pattern: Pattern, matched_keys: list[str]) -> bool:
        """Daha uzun bir kok zaten eslesmisse kisa varyanti tekrar raporlamaz."""
        key = pattern.key
        return any(key in other for other in matched_keys)

    def find(self, norm: NormalizedText) -> list[RawMatch]:
        """Metindeki tum kok eslesmelerini dondurur (kok basina en fazla bir)."""
        results: list[RawMatch] = []
        matched_keys: list[str] = []
        # Masum kalip icinde kalan kokler bastan devre disi (bkz. _phrase_suppressed).
        # Ayni kume tekrar eslesmeyi de onler: her kok en fazla bir kez raporlanir.
        matched: set[str] = self._phrase_suppressed(norm)

        # 1) kelime gecisi
        for token in norm.tokens:
            for pattern in self.patterns:
                if pattern.raw in matched or self._redundant(pattern, matched_keys):
                    continue
                folded = not pattern.keep_i
                hay = token.form.get(folded=folded, masked=False)
                text = self._accept(hay, _find_literal(hay, pattern), pattern)
                if text is not None:
                    matched.add(pattern.raw)
                    matched_keys.append(pattern.key)
                    results.append(
                        RawMatch(pattern, text, "token", obfuscated=False)
                    )
                    continue
                if token.form.has_mask:
                    hay_m = token.form.get(folded=folded, masked=True)
                    text = self._accept(hay_m, _find_wildcard(hay_m, pattern), pattern)
                    if text is not None:
                        matched.add(pattern.raw)
                        matched_keys.append(pattern.key)
                        results.append(
                            RawMatch(pattern, text, "token", obfuscated=True)
                        )

        # 2) birlesik gecis: SADECE cok kelimeli kokler ("amina koyayim").
        # Tek kelimelik kokleri burada aramak yanlis pozitif uretir
        # ("klasik tir..." -> "siktir"); onlar icin 3. gecis var.
        for pattern in self.patterns:
            if pattern.raw in matched or pattern.exact or not pattern.multiword:
                continue
            if self._redundant(pattern, matched_keys):
                continue
            if pattern.length < self.min_glue_length:
                continue
            folded = not pattern.keep_i
            hay = norm.glued.get(folded=folded, masked=False)
            text = self._accept(hay, _find_literal(hay, pattern), pattern)
            if text is not None:
                matched.add(pattern.raw)
                matched_keys.append(pattern.key)
                results.append(
                    RawMatch(pattern, text, "glue", obfuscated=not pattern.multiword)
                )
                continue
            if norm.glued.has_mask:
                hay_m = norm.glued.get(folded=folded, masked=True)
                text = self._accept(hay_m, _find_wildcard(hay_m, pattern), pattern)
                if text is not None:
                    matched.add(pattern.raw)
                    matched_keys.append(pattern.key)
                    results.append(RawMatch(pattern, text, "glue", obfuscated=True))

        # 3) aralikli gecis ("s i k t i r")
        for run in norm.runs:
            for pattern in self.patterns:
                if pattern.raw in matched or pattern.length < 2:
                    continue
                if self._redundant(pattern, matched_keys):
                    continue
                folded = not pattern.keep_i
                hay = run.get(folded=folded, masked=False)
                text = self._accept(hay, _find_literal(hay, pattern), pattern)
                if text is not None:
                    matched.add(pattern.raw)
                    matched_keys.append(pattern.key)
                    results.append(RawMatch(pattern, text, "run", obfuscated=True))
                    continue
                if run.has_mask:
                    hay_m = run.get(folded=folded, masked=True)
                    text = self._accept(hay_m, _find_wildcard(hay_m, pattern), pattern)
                    if text is not None:
                        matched.add(pattern.raw)
                        matched_keys.append(pattern.key)
                        results.append(RawMatch(pattern, text, "run", obfuscated=True))

        return self._drop_redundant(results)
