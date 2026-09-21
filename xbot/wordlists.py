"""Kelime listesi dosyalarini okuma ve dogrulama.

Dosyalar duz metin, UTF-8 ve elle duzenlenebilir olacak sekilde tasarlandi:
  * "#" ile baslayan satirlar ve bos satirlar yok sayilir
  * satir sonundaki " # aciklama" kismi atilir
  * kufur listesinde "kok | bayrak, bayrak" formati desteklenir
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .detector.matcher import KNOWN_FLAGS, Pattern, make_pattern
from .models import SEVERITY_BY_NAME, Severity

_SEVERITY_FLAGS = frozenset(SEVERITY_BY_NAME)


class WordListError(Exception):
    """Kelime listesi dosyasi okunamadi veya bozuk."""


@dataclass(frozen=True, slots=True)
class ProfanityEntry:
    """Kufur listesindeki tek satirin cozumlenmis hali."""

    raw: str
    severity: Severity
    exact: bool
    keep_i: bool
    line_no: int

    def to_pattern(self) -> Pattern:
        return make_pattern(
            self.raw, self.severity, exact=self.exact, keep_i=self.keep_i
        )


def _strip_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    head, sep, _tail = line.partition(" #")
    return (head if sep else line).strip()


def read_lines(path: str | Path) -> list[tuple[int, str]]:
    """Dosyayi okur; (satir numarasi, temizlenmis satir) listesi dondurur."""
    file_path = Path(path)
    if not file_path.exists():
        raise WordListError(f"Kelime listesi dosyası bulunamadı: {file_path}")
    try:
        content = file_path.read_text(encoding="utf-8-sig")
    except OSError as exc:  # pragma: no cover - dosya sistemi hatasi
        raise WordListError(f"Dosya okunamadı: {file_path} ({exc})") from exc
    out: list[tuple[int, str]] = []
    for number, raw_line in enumerate(content.splitlines(), start=1):
        cleaned = _strip_comment(raw_line)
        if cleaned:
            out.append((number, cleaned))
    return out


def load_word_list(path: str | Path) -> tuple[str, ...]:
    """Tek kelimelik listeleri okur (istisna listesi, olumlu baglam, beyaz liste)."""
    words = [line for _, line in read_lines(path)]
    # tekrarlari koru ama sirayi bozma
    return tuple(dict.fromkeys(words))


def parse_profanity_line(line: str, line_no: int = 0) -> ProfanityEntry:
    """'kok | bayraklar' satirini cozumler."""
    root, _, flag_part = line.partition("|")
    root = root.strip()
    if not root:
        raise WordListError(f"Satır {line_no}: kök boş olamaz → {line!r}")

    flags = {f.strip().lower() for f in flag_part.split(",") if f.strip()}
    unknown = flags - KNOWN_FLAGS
    if unknown:
        raise WordListError(
            f"Satır {line_no}: bilinmeyen bayrak(lar): {', '.join(sorted(unknown))}. "
            f"Geçerli bayraklar: {', '.join(sorted(KNOWN_FLAGS))}"
        )
    severity_flags = flags & _SEVERITY_FLAGS
    if len(severity_flags) > 1:
        raise WordListError(
            f"Satır {line_no}: tek bir ağırlık bayrağı kullan "
            f"({', '.join(sorted(severity_flags))} birlikte verilmis)"
        )
    severity = (
        SEVERITY_BY_NAME[next(iter(severity_flags))]
        if severity_flags
        else Severity.STRONG
    )
    return ProfanityEntry(
        raw=root,
        severity=severity,
        exact="exact" in flags,
        keep_i="keep_i" in flags,
        line_no=line_no,
    )


def load_profanity_entries(path: str | Path) -> list[ProfanityEntry]:
    """Kufur listesi dosyasini cozumler."""
    entries: list[ProfanityEntry] = []
    seen: dict[str, int] = {}
    for line_no, line in read_lines(path):
        entry = parse_profanity_line(line, line_no)
        if entry.raw.lower() in seen:
            # tekrar eden kok: sessizce atla, ilk taniminki gecerli
            continue
        seen[entry.raw.lower()] = line_no
        entries.append(entry)
    if not entries:
        raise WordListError(f"Küfür listesi boş: {path}")
    return entries


def load_profanity_patterns(path: str | Path) -> list[Pattern]:
    """Kufur listesini dogrudan eslestirme kaliplarina cevirir."""
    return [entry.to_pattern() for entry in load_profanity_entries(path)]
