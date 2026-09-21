"""Beyaz liste: bu hesaplar HICBIR KOSULDA engellenmez (madde 6).

Liste data/whitelist.txt dosyasindan okunur. "sync-whitelist" komutu takip
ettiklerini bu dosyaya ekleyebilir. Karsilastirma buyuk/kucuk harf ve "@"
farkina bakmaz.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .logging_setup import get_logger


def normalize_username(username: str) -> str:
    """'@Okan_Buruk' -> 'okan_buruk'"""
    return (username or "").strip().lstrip("@").lower()


class Whitelist:
    """Engellenmeyecek hesaplarin listesi."""

    def __init__(
        self,
        usernames: Iterable[str] = (),
        *,
        path: str | Path | None = None,
        logger=None,
    ) -> None:
        self.path = Path(path) if path else None
        self.logger = logger or get_logger("whitelist")
        self._names: set[str] = set()
        self._original: list[str] = []
        for name in usernames:
            clean = normalize_username(name)
            if clean and clean not in self._names:
                self._names.add(clean)
                self._original.append(name.strip().lstrip("@"))

    @classmethod
    def from_file(cls, path: str | Path, *, logger=None) -> "Whitelist":
        """Dosyadan okur. Dosya yoksa bos liste dondurur (hata vermez)."""
        from .wordlists import WordListError, load_word_list

        file_path = Path(path)
        try:
            names = load_word_list(file_path)
        except WordListError:
            names = ()
        return cls(names, path=file_path, logger=logger)

    # --- sorgu ---

    def contains(self, username: str) -> bool:
        return normalize_username(username) in self._names

    __contains__ = contains

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._original)

    def __len__(self) -> int:
        return len(self._names)

    def __bool__(self) -> bool:
        # Bos beyaz liste de gecerlidir; nesne her zaman "dogru" sayilir
        return True

    # --- guncelleme ---

    def add(self, username: str, *, write: bool = True) -> bool:
        """Listeye ekler. Zaten varsa False dondurur."""
        clean = normalize_username(username)
        if not clean or clean in self._names:
            return False
        self._names.add(clean)
        display = username.strip().lstrip("@")
        self._original.append(display)
        if write and self.path is not None:
            self._append_to_file([display])
        return True

    def add_many(self, usernames: Iterable[str], *, write: bool = True) -> int:
        """Birden fazla hesabi ekler; eklenen sayisini dondurur."""
        added: list[str] = []
        for username in usernames:
            clean = normalize_username(username)
            if not clean or clean in self._names:
                continue
            self._names.add(clean)
            display = username.strip().lstrip("@")
            self._original.append(display)
            added.append(display)
        if added and write and self.path is not None:
            self._append_to_file(added)
        return len(added)

    def _append_to_file(self, names: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = ""
        if self.path.exists():
            existing = self.path.read_text(encoding="utf-8-sig")
        prefix = "" if (not existing or existing.endswith("\n")) else "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(prefix + "\n".join(names) + "\n")
        self.logger.info("Beyaz listeye %d hesap eklendi: %s", len(names), self.path)
