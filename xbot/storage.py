"""SQLite kayitlari: gorulen tweetler, engellenenler, supheliler, calisma gecmisi.

Neden kayit tutuyoruz?
  * Ayni tweeti/hesabi ikinci kez islememek (spesifikasyon madde 7)
  * Saatlik/gunluk engelleme limitlerini saymak (madde 2)
  * Yanlis bir engellemeyi geri alabilmek icin KANIT tutmak (madde 8):
    hesap adi, tweet metni, tweet linki, zaman, eslesen kural
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Decision, Level, Tweet

SCHEMA_VERSION = 1

SUSPECT_PENDING = "pending"
SUSPECT_BLOCKED = "blocked"
SUSPECT_DISMISSED = "dismissed"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_tweets (
    tweet_id   TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    text       TEXT,
    tweet_time TEXT,
    url        TEXT,
    level      TEXT,
    rules      TEXT,
    query      TEXT,
    seen_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS seen_tweets_user ON seen_tweets (username);

CREATE TABLE IF NOT EXISTS suspects (
    tweet_id   TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    text       TEXT,
    url        TEXT,
    tweet_time TEXT,
    rules      TEXT,
    reasons    TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS suspects_status ON suspects (status);

CREATE TABLE IF NOT EXISTS blocks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    tweet_id   TEXT,
    text       TEXT,
    url        TEXT,
    tweet_time TEXT,
    rules      TEXT,
    reasons    TEXT,
    level      TEXT,
    mode       TEXT,
    blocked_at TEXT NOT NULL,
    undone     INTEGER NOT NULL DEFAULT 0,
    note       TEXT
);
CREATE INDEX IF NOT EXISTS blocks_user ON blocks (username);
CREATE INDEX IF NOT EXISTS blocks_time ON blocks (blocked_at);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    mode        TEXT,
    queries     TEXT,
    seen        INTEGER DEFAULT 0,
    high        INTEGER DEFAULT 0,
    suspect     INTEGER DEFAULT 0,
    blocked     INTEGER DEFAULT 0,
    skipped     INTEGER DEFAULT 0,
    status      TEXT,
    message     TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class BlockRecord:
    """Engelleme kaydi (rapor ve geri alma icin)."""

    id: int
    username: str
    tweet_id: str
    text: str
    url: str
    tweet_time: str
    rules: str
    reasons: str
    level: str
    mode: str
    blocked_at: str
    undone: bool = False
    note: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "BlockRecord":
        return cls(
            id=row["id"],
            username=row["username"],
            tweet_id=row["tweet_id"] or "",
            text=row["text"] or "",
            url=row["url"] or "",
            tweet_time=row["tweet_time"] or "",
            rules=row["rules"] or "",
            reasons=row["reasons"] or "",
            level=row["level"] or "",
            mode=row["mode"] or "",
            blocked_at=row["blocked_at"],
            undone=bool(row["undone"]),
            note=row["note"] or "",
        )

    def undo_hint(self) -> str:
        """Engeli elle geri almak icin gereken bilgi."""
        return (
            f"@{self.username} — engel kaldırmak için: "
            f"https://x.com/{self.username} sayfasında 'Engeli kaldır'. "
            f"Kanıt tweet: {self.url or '(bağlantı yok)'}"
        )


@dataclass(frozen=True, slots=True)
class SuspectRecord:
    """Suphelı tweet kaydi (review komutu icin)."""

    tweet_id: str
    username: str
    text: str
    url: str
    tweet_time: str
    rules: str
    reasons: str
    status: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SuspectRecord":
        return cls(
            tweet_id=row["tweet_id"],
            username=row["username"],
            text=row["text"] or "",
            url=row["url"] or "",
            tweet_time=row["tweet_time"] or "",
            rules=row["rules"] or "",
            reasons=row["reasons"] or "",
            status=row["status"],
            created_at=row["created_at"],
        )

    def as_tweet(self) -> Tweet:
        from .timefilter import parse_tweet_time

        return Tweet(
            tweet_id=self.tweet_id,
            username=self.username,
            text=self.text,
            created_at=parse_tweet_time(self.tweet_time),
            url=self.url or None,
        )


class Storage:
    """SQLite sarmalayicisi. Kullanim: with Storage(path) as db: ..."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # --- baglanti ---

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
        self._conn = conn
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connect()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Storage":
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # --- gorulen tweetler ---

    def is_seen(self, tweet_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen_tweets WHERE tweet_id = ?", (tweet_id,)
        ).fetchone()
        return row is not None

    def mark_seen(
        self,
        tweet: Tweet,
        *,
        level: Level | None = None,
        rules: str = "",
        query: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO seen_tweets
                (tweet_id, username, text, tweet_time, url, level, rules, query, seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tweet_id) DO UPDATE SET
                level = excluded.level,
                rules = excluded.rules,
                query = excluded.query,
                seen_at = excluded.seen_at
            """,
            (
                tweet.tweet_id,
                tweet.username,
                tweet.text,
                _iso(tweet.created_at),
                tweet.url,
                level.name if level is not None else None,
                rules,
                query,
                _now(),
            ),
        )
        self.conn.commit()

    def seen_count(self) -> int:
        return int(
            self.conn.execute("SELECT COUNT(*) AS n FROM seen_tweets").fetchone()["n"]
        )

    # --- engellemeler ---

    def is_blocked(self, username: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM blocks WHERE lower(username) = ? AND undone = 0",
            (username.lstrip("@").lower(),),
        ).fetchone()
        return row is not None

    def record_block(
        self,
        tweet: Tweet,
        decision: Decision | None = None,
        *,
        mode: str = "auto",
        note: str = "",
        rules: str | None = None,
    ) -> int:
        rule_text = rules if rules is not None else (decision.rule_summary if decision else "")
        cursor = self.conn.execute(
            """
            INSERT INTO blocks
                (username, tweet_id, text, url, tweet_time, rules, reasons, level,
                 mode, blocked_at, undone, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                tweet.username,
                tweet.tweet_id,
                tweet.text,
                tweet.url,
                _iso(tweet.created_at),
                rule_text,
                " | ".join(decision.reasons) if decision else "",
                decision.level.name if decision else "",
                mode,
                _now(),
                note,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def blocks_since(self, moment: datetime) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM blocks WHERE blocked_at >= ? AND undone = 0",
            (_iso(moment),),
        ).fetchone()
        return int(row["n"])

    def blocks_last_hour(self, *, now: datetime | None = None) -> int:
        reference = now or datetime.now(timezone.utc)
        return self.blocks_since(reference - timedelta(hours=1))

    def blocks_last_day(self, *, now: datetime | None = None) -> int:
        reference = now or datetime.now(timezone.utc)
        return self.blocks_since(reference - timedelta(days=1))

    def recent_blocks(self, limit: int = 50, *, include_undone: bool = True) -> list[BlockRecord]:
        query = "SELECT * FROM blocks"
        if not include_undone:
            query += " WHERE undone = 0"
        query += " ORDER BY id DESC LIMIT ?"
        rows = self.conn.execute(query, (limit,)).fetchall()
        return [BlockRecord.from_row(row) for row in rows]

    def mark_block_undone(self, block_id: int, *, note: str = "") -> bool:
        cursor = self.conn.execute(
            "UPDATE blocks SET undone = 1, note = ? WHERE id = ?",
            (note or "elle geri alındı", block_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # --- supheliler ---

    def add_suspect(self, tweet: Tweet, decision: Decision) -> None:
        self.conn.execute(
            """
            INSERT INTO suspects
                (tweet_id, username, text, url, tweet_time, rules, reasons,
                 status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tweet_id) DO UPDATE SET
                rules = excluded.rules,
                reasons = excluded.reasons
            """,
            (
                tweet.tweet_id,
                tweet.username,
                tweet.text,
                tweet.url,
                _iso(tweet.created_at),
                decision.rule_summary,
                " | ".join(decision.reasons),
                SUSPECT_PENDING,
                _now(),
            ),
        )
        self.conn.commit()

    def pending_suspects(self, limit: int = 100) -> list[SuspectRecord]:
        rows = self.conn.execute(
            "SELECT * FROM suspects WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (SUSPECT_PENDING, limit),
        ).fetchall()
        return [SuspectRecord.from_row(row) for row in rows]

    def all_suspects(self, limit: int = 500) -> list[SuspectRecord]:
        rows = self.conn.execute(
            "SELECT * FROM suspects ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [SuspectRecord.from_row(row) for row in rows]

    def set_suspect_status(self, tweet_id: str, status: str) -> bool:
        if status not in (SUSPECT_PENDING, SUSPECT_BLOCKED, SUSPECT_DISMISSED):
            raise ValueError(f"Geçersiz şüpheli durumu: {status}")
        cursor = self.conn.execute(
            "UPDATE suspects SET status = ?, decided_at = ? WHERE tweet_id = ?",
            (status, _now(), tweet_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # --- calisma gecmisi ---

    def start_run(self, *, mode: str, queries: Sequence[str]) -> int:
        cursor = self.conn.execute(
            "INSERT INTO runs (started_at, mode, queries, status) VALUES (?, ?, ?, ?)",
            (_now(), mode, ", ".join(queries), "running"),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        seen: int = 0,
        high: int = 0,
        suspect: int = 0,
        blocked: int = 0,
        skipped: int = 0,
        status: str = "ok",
        message: str = "",
    ) -> None:
        self.conn.execute(
            """
            UPDATE runs SET finished_at = ?, seen = ?, high = ?, suspect = ?,
                            blocked = ?, skipped = ?, status = ?, message = ?
            WHERE id = ?
            """,
            (_now(), seen, high, suspect, blocked, skipped, status, message, run_id),
        )
        self.conn.commit()

    def last_runs(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    # --- istatistik ---

    def stats(self) -> dict[str, int | str]:
        conn = self.conn
        def scalar(sql: str, params: Iterable = ()) -> int:
            row = conn.execute(sql, tuple(params)).fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        last_run = conn.execute(
            "SELECT started_at, mode, status FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "gorulen_tweet": scalar("SELECT COUNT(*) FROM seen_tweets"),
            "engellenen": scalar("SELECT COUNT(*) FROM blocks WHERE undone = 0"),
            "geri_alinan": scalar("SELECT COUNT(*) FROM blocks WHERE undone = 1"),
            "supheli_bekleyen": scalar(
                "SELECT COUNT(*) FROM suspects WHERE status = 'pending'"
            ),
            "supheli_engellenen": scalar(
                "SELECT COUNT(*) FROM suspects WHERE status = 'blocked'"
            ),
            "supheli_temizlenen": scalar(
                "SELECT COUNT(*) FROM suspects WHERE status = 'dismissed'"
            ),
            "son_1_saat_engel": self.blocks_last_hour(),
            "son_24_saat_engel": self.blocks_last_day(),
            "calisma_sayisi": scalar("SELECT COUNT(*) FROM runs"),
            "son_calisma": (
                f"{last_run['started_at']} ({last_run['mode']}, {last_run['status']})"
                if last_run
                else "(hiç çalışmadı)"
            ),
        }
