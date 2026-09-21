"""Ortak veri modelleri: Tweet, Match, Verdict, Decision.

Bu modeller hem dedektorler hem de (sonraki asamalarda) scraper,
storage ve report tarafindan paylasilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class Level(IntEnum):
    """Bir tweet icin verilen karar seviyesi."""

    CLEAN = 0
    SUSPECT = 1
    HIGH = 2

    @property
    def label(self) -> str:
        """Kullaniciya gosterilecek Turkce etiket."""
        return _LEVEL_LABELS[self]


_LEVEL_LABELS = {
    Level.CLEAN: "TEMİZ",
    Level.SUSPECT: "ŞÜPHELİ",
    Level.HIGH: "YÜKSEK",
}


class Severity(IntEnum):
    """Kelime listesindeki bir kokun agirligi."""

    AMBIGUOUS = 1  # belirsiz: sevincle de kullanilabilir ("amk gol")
    MILD = 2  # hafif hakaret ("salak")
    STRONG = 3  # acik ve net kufur ("siktir")

    @property
    def label(self) -> str:
        return _SEVERITY_LABELS[self]


_SEVERITY_LABELS = {
    Severity.AMBIGUOUS: "belirsiz",
    Severity.MILD: "hafif",
    Severity.STRONG: "güçlü",
}

SEVERITY_BY_NAME = {
    "ambiguous": Severity.AMBIGUOUS,
    "mild": Severity.MILD,
    "strong": Severity.STRONG,
}


@dataclass(frozen=True, slots=True)
class Tweet:
    """Tek bir tweet. Scraper bu nesneyi uretir, dedektorler tuketir."""

    tweet_id: str
    username: str
    text: str
    created_at: datetime | None = None
    url: str | None = None
    display_name: str = ""

    def __post_init__(self) -> None:
        clean_user = self.username.strip().lstrip("@")
        if clean_user != self.username:
            object.__setattr__(self, "username", clean_user)
        if not self.url and self.tweet_id and clean_user:
            object.__setattr__(
                self, "url", f"https://x.com/{clean_user}/status/{self.tweet_id}"
            )

    @property
    def permalink(self) -> str:
        return self.url or ""


@dataclass(frozen=True, slots=True)
class Match:
    """Bir dedektorun buldugu tek bir eslesme (kanit)."""

    detector: str
    rule: str  # listede yazdigi haliyle kok / isim
    severity: Severity
    matched_text: str  # metinde normalize edilmis haliyle bulunan parca
    source: str = "token"  # token | glue | run  (nerede bulundu)
    obfuscated: bool = False  # yildiz/nokta/bosluk ile gizlenmis mi
    note: str = ""

    @property
    def explanation(self) -> str:
        """Rapor ve loglar icin Turkce tek satirlik aciklama."""
        where = {
            "token": "kelime içinde",
            "glue": "birleşik metinde",
            "run": "aralıklı yazımda",
        }.get(self.source, self.source)
        extra = " (gizlenmiş yazım)" if self.obfuscated else ""
        note = f" [{self.note}]" if self.note else ""
        return (
            f"{self.severity.label} eşleşme '{self.rule}'"
            f" → '{self.matched_text}' ({where}){extra}{note}"
        )


@dataclass(frozen=True, slots=True)
class Verdict:
    """Tek bir dedektorun cikardigi sonuc."""

    detector: str
    level: Level = Level.CLEAN
    matches: tuple[Match, ...] = ()
    reasons: tuple[str, ...] = ()
    flags: frozenset[str] = frozenset()

    @property
    def max_severity(self) -> Severity | None:
        if not self.matches:
            return None
        return max(m.severity for m in self.matches)

    @classmethod
    def clean(cls, detector: str, flags: frozenset[str] = frozenset()) -> "Verdict":
        return cls(detector=detector, level=Level.CLEAN, flags=flags)


@dataclass(frozen=True, slots=True)
class Decision:
    """Butun dedektorlerin birlestirilmis nihai karari."""

    tweet: Tweet
    level: Level
    matches: tuple[Match, ...] = ()
    reasons: tuple[str, ...] = ()
    flags: frozenset[str] = frozenset()
    verdicts: tuple[Verdict, ...] = ()

    @property
    def is_blockable(self) -> bool:
        """Sadece HIGH kararlar otomatik engellenebilir."""
        return self.level is Level.HIGH

    @property
    def target_hit(self) -> bool:
        return "target" in self.flags

    @property
    def rule_summary(self) -> str:
        """Kayitlara yazilacak kisa kural ozeti."""
        if not self.matches:
            return ""
        return ", ".join(dict.fromkeys(m.rule for m in self.matches))

    def describe(self) -> str:
        """Terminalde gosterilecek cok satirli aciklama."""
        lines = [f"Karar: {self.level.label}"]
        lines.extend(f"  - {r}" for r in self.reasons)
        return "\n".join(lines)


@dataclass
class DetectionStats:
    """Bir tarama turunun sayaclari (rapor ve loglar icin)."""

    seen: int = 0
    clean: int = 0
    suspect: int = 0
    high: int = 0
    skipped_old: int = 0
    skipped_known: int = 0
    skipped_whitelist: int = 0
    extra: dict[str, int] = field(default_factory=dict)

    def add(self, level: Level) -> None:
        self.seen += 1
        if level is Level.HIGH:
            self.high += 1
        elif level is Level.SUSPECT:
            self.suspect += 1
        else:
            self.clean += 1
