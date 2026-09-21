"""Turkce metin normalizasyonu.

Amac: kufur tespitinden kacmak icin kullanilan yazim oyunlarini tek bir
karsilastirilabilir bicime indirmek.

Ele alinan durumlar:
  * Buyuk/kucuk harf (Turkce kurallari: I -> kucuk noktasiz i, buyuk noktali I -> i)
  * Turkce karakterler (s-cedilla -> s, c-cedilla -> c, g-breve -> g, o/u-umlaut -> o/u)
  * Harf yerine rakam/sembol ("s1k", "am@na", "$erefsiz")
  * Tekrar eden harfler ("amkkkk" -> "amk")
  * Araya konan nokta/yildiz/alt cizgi ("a.m.k" -> "amk")
  * Harf yerine maske karakteri ("s*k" -> joker ile eslesir)
  * Kelimeleri aralikli yazma ("s i k t i r")

Her metin icin dort bicim uretilir:
  plain          : noktasiz i ile noktali i ayri tutulur, ayiricilar silinir
  folded         : ek olarak noktasiz i -> i  ("sikinti" ile "sikinti" ayni olur)
  plain_masked   : ayirici karakterler "herhangi bir harf" jokerine donusur
  folded_masked  : ikisinin birlesimi

Dedektor, kok listesindeki bayraklara gore hangi bicimi kullanacagina karar
verir (bkz. detector/matcher.py).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Joker karakter: "herhangi bir harf" anlamina gelir.
WILDCARD = "\x00"

# --- karakter siniflari ---
_LETTER = "L"
_SEP = "S"  # silinebilir VEYA harf yerine gecmis olabilir (maske)
_DROP = "X"  # tamamen atilir (emoji vb.), maske olamaz

# Turkce buyuk harf donusumu (str.lower() bunu Turkce kurallarina gore yapmaz)
_TR_UPPER = {"I": "ı", "İ": "i"}

# Turkce/aksanli harflerin sadelestirilmesi. Noktasiz i bilincli olarak
# DISARIDA: i ayrimi "sikinti" gibi masum kelimeler icin kritik.
_SIMPLIFY = {
    "ş": "s",  # s-cedilla
    "ç": "c",  # c-cedilla
    "ğ": "g",  # g-breve
    "ö": "o",
    "ü": "u",
    "â": "a",
    "ä": "a",
    "à": "a",
    "á": "a",
    "å": "a",
    "ê": "e",
    "é": "e",
    "è": "e",
    "ë": "e",
    "î": "i",
    "í": "i",
    "ì": "i",
    "ï": "i",
    "ô": "o",
    "ó": "o",
    "ò": "o",
    "õ": "o",
    "ø": "o",
    "û": "u",
    "ú": "u",
    "ù": "u",
    "ñ": "n",
    "ý": "y",
    "ÿ": "y",
    "ß": "s",
    # Kiril/Yunan benzeri harfler (gorsel taklit)
    "а": "a",
    "е": "e",
    "о": "o",
    "с": "c",
    "р": "p",
    "у": "u",
    "х": "x",
    "ѕ": "s",
    "і": "i",
    "к": "k",
    "м": "m",
    "т": "t",
    "α": "a",
    "ο": "o",
    "ι": "i",
}

# Harf yerine kullanilan rakam/sembol ("leet"). Sadece icinde harf de bulunan
# kelimelerde uygulanir ki "2-0" gibi skorlar bozulmasin.
_LEET = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "9": "g",
    "@": "a",
    "$": "s",
    "€": "e",
}

# Kelimeyi bolen karakterler (bunlar maske olamaz)
_SPLIT_CHARS = set(",;:()[]{}<>/|\\\n\r\t \"'`«»…“”‘’")

# Harf yerine gecmis olabilecek ("maske") karakterler
_MASK_CHARS = set("*#.-_+%&?!~^=·•²³")

# Gorunmez karakterler
_INVISIBLE = {"​", "‌", "‍", "﻿", "⁠", "­"}


def _tr_lower(text: str) -> str:
    """Turkce kurallarina gore kucuk harfe cevirir."""
    return "".join(_TR_UPPER.get(ch, ch) for ch in text).lower()


def collapse_repeats(text: str) -> str:
    """Ust uste gelen ayni karakterleri tek karaktere indirir."""
    if not text:
        return text
    out = [text[0]]
    for ch in text[1:]:
        if ch != out[-1]:
            out.append(ch)
    return "".join(out)


def fold_i(text: str) -> str:
    """Noktasiz i -> i donusumu (gevsek karsilastirma bicimi)."""
    return text.replace("ı", "i")


@dataclass(frozen=True, slots=True)
class Form:
    """Bir metnin karsilastirmaya hazir dort bicimi."""

    plain: str
    folded: str
    plain_masked: str
    folded_masked: str

    def get(self, *, folded: bool, masked: bool) -> str:
        if folded:
            return self.folded_masked if masked else self.folded
        return self.plain_masked if masked else self.plain

    @property
    def length(self) -> int:
        return len(self.plain)

    @property
    def has_mask(self) -> bool:
        return WILDCARD in self.plain_masked


EMPTY_FORM = Form("", "", "", "")


@dataclass(frozen=True, slots=True)
class Token:
    """Metindeki tek bir kelime."""

    index: int
    original: str
    form: Form

    @property
    def length(self) -> int:
        return self.form.length


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """Normalize edilmis metin: kelimeler + birlesik bicimler."""

    original: str
    tokens: tuple[Token, ...]
    glued: Form  # tum kelimeler bitisik ("aminakoyayim")
    runs: tuple[Form, ...]  # "s i k t i r" gibi aralikli yazimlarin birlesimi

    @property
    def is_empty(self) -> bool:
        return not self.glued.plain


def _classify(raw_token: str) -> list[tuple[str, str]]:
    """Kelimenin karakterlerini (sinif, deger) listesine cevirir."""
    lowered = _tr_lower(raw_token)
    has_letter = any(ch.isalpha() for ch in lowered)
    chars: list[tuple[str, str]] = []
    for ch in lowered:
        if ch in _INVISIBLE:
            continue
        if ch.isalpha():
            chars.append((_LETTER, _SIMPLIFY.get(ch, ch)))
        elif has_letter and ch in _LEET:
            chars.append((_LETTER, _LEET[ch]))
        elif ch.isdigit() or ch in _MASK_CHARS or ch in _LEET:
            # rakamlar da harf yerine kullanilabilir: "s2k"
            chars.append((_SEP, ch))
        elif ch in _SPLIT_CHARS:
            chars.append((_SEP, ch))
        else:
            chars.append((_DROP, ch))
    return chars


def _assemble(chars: list[tuple[str, str]]) -> Form:
    """(sinif, deger) listesinden dort bicimi uretir."""
    plain: list[str] = []
    masked: list[str] = []
    pending_sep = False
    for kind, value in chars:
        if kind == _LETTER:
            if pending_sep and masked:
                masked.append(WILDCARD)
            pending_sep = False
            plain.append(value)
            masked.append(value)
        elif kind == _SEP:
            pending_sep = True
        else:  # _DROP: maskelemeyi de bozar
            pending_sep = False
    plain_s = collapse_repeats("".join(plain))
    masked_s = collapse_repeats("".join(masked))
    return Form(
        plain=plain_s,
        folded=fold_i(plain_s),
        plain_masked=masked_s,
        folded_masked=fold_i(masked_s),
    )


def _concat(forms: list[Form]) -> Form:
    """Birden fazla kelimeyi bitistirir (arada joker olusturmadan)."""
    if not forms:
        return EMPTY_FORM
    plain_s = collapse_repeats("".join(f.plain for f in forms))
    masked_s = collapse_repeats("".join(f.plain_masked for f in forms))
    return Form(
        plain=plain_s,
        folded=fold_i(plain_s),
        plain_masked=masked_s,
        folded_masked=fold_i(masked_s),
    )


def split_tokens(text: str) -> list[str]:
    """Metni ham kelimelere boler (bolucu karakterlerden)."""
    tokens: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch in _SPLIT_CHARS or ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def normalize_pattern(text: str) -> Form:
    """Kok/isim gibi bir kalibi normalize eder (bosluklar silinir)."""
    forms = [_assemble(_classify(tok)) for tok in split_tokens(text)]
    forms = [f for f in forms if f.plain]
    return _concat(forms)


def normalize_text(text: str, *, max_run_token_length: int = 2) -> NormalizedText:
    """Tweet metnini normalize eder.

    max_run_token_length: "aralikli yazim" birlestirmesine dahil edilecek en
    fazla kelime uzunlugu. Varsayilan 2: "s i k t i r" veya "am k" birlestirilir,
    normal kelimeler birbirine yapistirilmaz.
    """
    raw_tokens = split_tokens(text)
    tokens: list[Token] = []
    for raw in raw_tokens:
        stripped = raw.lstrip("@#")
        form = _assemble(_classify(stripped))
        if not form.plain:
            continue
        tokens.append(Token(index=len(tokens), original=raw, form=form))

    glued = _concat([t.form for t in tokens])

    runs: list[Form] = []
    current: list[Form] = []
    for token in tokens:
        if token.length <= max_run_token_length:
            current.append(token.form)
        else:
            if len(current) >= 2:
                runs.append(_concat(current))
            current = []
    if len(current) >= 2:
        runs.append(_concat(current))

    return NormalizedText(
        original=text,
        tokens=tuple(tokens),
        glued=glued,
        runs=tuple(runs),
    )
