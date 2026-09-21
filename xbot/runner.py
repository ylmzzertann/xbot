"""Tarama turunu yoneten katman.

Sira: arama sayfasini tara -> zaman filtresi -> karar -> (dry-run/auto) aksiyon
-> kayit. Tarayici islerini "scrape" callable'i yapar; boylece bu sinif
tarayicidan bagimsiz test edilebilir.

Beklenmeyen bir durumda (CAPTCHA, degisen secici, dogrulanamayan engelleme)
StopRun yukselir: tur guvenli bicimde biter, sebep kaydedilir ve istege bagli
masaustu bildirimi gonderilir.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .actions import STATUS_ALREADY, STATUS_DRY_RUN, STATUS_LIMIT, STATUS_WHITELISTED
from .errors import StopRun
from .logging_setup import get_logger
from .models import Decision, Level, Tweet
from .scraper import ScrapeResult
from .timefilter import TimeWindow


@dataclass
class RunSummary:
    """Bir turun sonucu (rapor ve terminal ozeti icin)."""

    mode: str
    queries: tuple[str, ...] = ()
    window_minutes: int = 60
    seen: int = 0
    in_window: int = 0
    clean: int = 0
    suspect: int = 0
    high: int = 0
    blocked: int = 0
    would_block: int = 0
    skipped_seen: int = 0
    skipped_whitelist: int = 0
    skipped_already: int = 0
    limited: int = 0
    stopped: bool = False
    stop_reason: str = ""
    run_id: int | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    scrape_results: list[ScrapeResult] = field(default_factory=list)
    decisions: list[tuple[Tweet, Decision]] = field(default_factory=list)

    @property
    def is_dry_run(self) -> bool:
        return self.mode != "auto"

    def lines(self) -> list[str]:
        """Terminalde gosterilecek ozet satirlari."""
        out = [
            f"Mod: {self.mode} ({'engellemedi' if self.is_dry_run else 'ENGELLEDİ'})",
            f"Aranan kelimeler: {', '.join(self.queries) or '(yok)'}",
            f"Zaman penceresi: son {self.window_minutes} dakika",
            f"Görülen tweet: {self.seen} (pencere içinde {self.in_window})",
            f"Temiz: {self.clean} | Şüpheli: {self.suspect} | Yüksek: {self.high}",
        ]
        if self.is_dry_run:
            out.append(f"Engellenecekti: {self.would_block}")
        else:
            out.append(f"Engellenen: {self.blocked}")
        if self.skipped_seen:
            out.append(f"Daha önce işlenmiş (atlandı): {self.skipped_seen}")
        if self.skipped_whitelist:
            out.append(f"Beyaz listede (atlandı): {self.skipped_whitelist}")
        if self.skipped_already:
            out.append(f"Zaten engelli (atlandı): {self.skipped_already}")
        if self.limited:
            out.append(f"Limit dolduğu için şüpheliye yazıldı: {self.limited}")
        if self.stopped:
            out.append(f"DURDU: {self.stop_reason}")
        return out

    def status(self) -> str:
        if self.stopped:
            return "stopped"
        return "ok"


class Runner:
    """Arama kelimelerini sirayla tarar ve karar uygular."""

    def __init__(
        self,
        config,
        *,
        engine,
        storage,
        whitelist,
        limiter,
        blocker,
        scrape: Callable[[str, TimeWindow], ScrapeResult],
        logger=None,
        notifier: Callable[[str, str], None] | None = None,
    ) -> None:
        self.config = config
        self.engine = engine
        self.storage = storage
        self.whitelist = whitelist
        self.limiter = limiter
        self.blocker = blocker
        self.scrape = scrape
        self.logger = logger or get_logger("runner")
        self.notifier = notifier

    # --- ana dongu ---

    def run(
        self,
        *,
        auto: bool = False,
        queries: Sequence[str] | None = None,
        window: TimeWindow | None = None,
    ) -> RunSummary:
        query_list = tuple(queries if queries is not None else self.config.search_queries)
        mode = "auto" if auto else "dry-run"
        time_window = window or TimeWindow.last_minutes(self.config.time_window_minutes)
        summary = RunSummary(
            mode=mode,
            queries=query_list,
            window_minutes=time_window.minutes,
        )
        if self.storage is not None:
            summary.run_id = self.storage.start_run(mode=mode, queries=query_list)

        self.logger.info(
            "Tur başlıyor — mod: %s, kelime sayısı: %d, pencere: %s",
            mode,
            len(query_list),
            time_window.describe(),
        )
        try:
            for index, query in enumerate(query_list):
                result = self.scrape(query, time_window)
                summary.scrape_results.append(result)
                summary.seen += result.total_seen
                summary.in_window += result.count
                for tweet in result.tweets:
                    self._handle_tweet(tweet, query, summary, auto=auto)
                if index < len(query_list) - 1 and self.limiter is not None:
                    self.limiter.wait_between_queries()
        except StopRun as exc:
            summary.stopped = True
            summary.stop_reason = str(exc)
            self.logger.error("Tur durduruldu: %s", exc)
            self._notify("XBot durdu", str(exc))
        finally:
            summary.finished_at = datetime.now(timezone.utc)
            if self.storage is not None and summary.run_id is not None:
                self.storage.finish_run(
                    summary.run_id,
                    seen=summary.seen,
                    high=summary.high,
                    suspect=summary.suspect,
                    blocked=summary.blocked,
                    skipped=summary.skipped_seen + summary.skipped_whitelist,
                    status=summary.status(),
                    message=summary.stop_reason,
                )
        for line in summary.lines():
            self.logger.info(line)
        return summary

    # --- tek tweet ---

    def _handle_tweet(
        self, tweet: Tweet, query: str, summary: RunSummary, *, auto: bool
    ) -> None:
        if self.storage is not None and self.storage.is_seen(tweet.tweet_id):
            summary.skipped_seen += 1
            return

        if self.whitelist is not None and self.whitelist.contains(tweet.username):
            summary.skipped_whitelist += 1
            if self.storage is not None:
                self.storage.mark_seen(tweet, level=Level.CLEAN, rules="beyaz liste", query=query)
            return

        decision = self.engine.evaluate(tweet)
        summary.decisions.append((tweet, decision))
        if self.storage is not None:
            self.storage.mark_seen(
                tweet,
                level=decision.level,
                rules=decision.rule_summary,
                query=query,
            )

        if decision.level is Level.HIGH:
            summary.high += 1
            self._act_on_high(tweet, decision, summary, auto=auto)
        elif decision.level is Level.SUSPECT:
            summary.suspect += 1
            if self.storage is not None:
                self.storage.add_suspect(tweet, decision)
        else:
            summary.clean += 1

    def _act_on_high(
        self, tweet: Tweet, decision: Decision, summary: RunSummary, *, auto: bool
    ) -> None:
        if self.blocker is None:
            summary.would_block += 1
            return
        outcome = self.blocker.block(tweet, decision, mode="auto" if auto else "dry-run")
        if outcome.blocked:
            summary.blocked += 1
        elif outcome.status == STATUS_DRY_RUN:
            summary.would_block += 1
        elif outcome.status == STATUS_LIMIT:
            summary.limited += 1
            if self.storage is not None:
                self.storage.add_suspect(tweet, decision)
        elif outcome.status == STATUS_WHITELISTED:
            summary.skipped_whitelist += 1
        elif outcome.status == STATUS_ALREADY:
            summary.skipped_already += 1

    # --- bildirim ---

    def _notify(self, title: str, message: str) -> None:
        if self.notifier is None:
            return
        try:
            self.notifier(title, message)
        except Exception as exc:  # pragma: no cover - bildirim kritik degil
            self.logger.debug("Bildirim gönderilemedi: %s", exc)
