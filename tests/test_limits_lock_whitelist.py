"""Limit, kilit ve beyaz liste testleri (guvenlik frenleri)."""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta, timezone

import pytest

from xbot.config import Delays, Limits
from xbot.errors import LockError
from xbot.lock import RunLock, pid_alive
from xbot.ratelimit import RateLimiter
from xbot.whitelist import Whitelist, normalize_username

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


class FakeStorage:
    """Sadece engelleme sayaclarini taklit eder."""

    def __init__(self, hour: int = 0, day: int = 0) -> None:
        self.hour = hour
        self.day = day

    def blocks_last_hour(self, *, now=None) -> int:
        return self.hour

    def blocks_last_day(self, *, now=None) -> int:
        return self.day


def make_limiter(*, hour=0, day=0, per_hour=10, per_day=40, sleeps=None):
    return RateLimiter(
        Limits(per_hour=per_hour, per_day=per_day),
        Delays(between_actions=(8, 25), between_scrolls=(2, 5)),
        storage=FakeStorage(hour, day),
        sleeper=(sleeps.append if sleeps is not None else (lambda _s: None)),
        rng=random.Random(42),
        clock=lambda: NOW,
    )


class TestRateLimits:
    def test_allowed_when_below_limits(self):
        status = make_limiter(hour=3, day=10).status()
        assert status.allowed is True
        assert status.left_hour == 7
        assert status.left_day == 30

    def test_hourly_limit_blocks(self):
        status = make_limiter(hour=10, day=10).status()
        assert status.allowed is False
        assert "Saatlik" in status.reason

    def test_daily_limit_blocks(self):
        status = make_limiter(hour=1, day=40).status()
        assert status.allowed is False
        assert "Günlük" in status.reason

    def test_zero_limit_disables_blocking(self):
        status = make_limiter(per_hour=0).status()
        assert status.allowed is False
        assert "kapalı" in status.reason

    def test_describe_is_readable(self):
        assert make_limiter(hour=2, day=5).status().describe() == (
            "saatlik 2/10, günlük 5/40"
        )

    def test_counts_without_storage(self):
        limiter = RateLimiter(
            Limits(per_hour=2, per_day=5),
            Delays(),
            sleeper=lambda _s: None,
            clock=lambda: NOW,
        )
        assert limiter.status().allowed is True
        limiter.register_block()
        limiter.register_block()
        assert limiter.status().allowed is False

    def test_old_blocks_do_not_count(self):
        times = [NOW - timedelta(hours=2)]
        limiter = RateLimiter(
            Limits(per_hour=1, per_day=5),
            Delays(),
            sleeper=lambda _s: None,
            clock=lambda: NOW,
        )
        limiter._history.extend(times)
        assert limiter.status().allowed is True


class TestDelays:
    def test_action_delay_within_range(self):
        sleeps: list[float] = []
        limiter = make_limiter(sleeps=sleeps)
        duration = limiter.wait_between_actions()
        assert 8 <= duration <= 25
        assert sleeps and sleeps[0] == duration

    def test_scroll_delay_within_range(self):
        sleeps: list[float] = []
        duration = make_limiter(sleeps=sleeps).wait_between_scrolls()
        assert 2 <= duration <= 5

    def test_delays_are_random(self):
        limiter = make_limiter()
        values = {limiter.wait_between_actions() for _ in range(10)}
        assert len(values) > 1  # sabit degil

    def test_equal_bounds_gives_fixed_delay(self):
        limiter = RateLimiter(
            Limits(),
            Delays(between_actions=(5, 5), between_scrolls=(1, 1)),
            sleeper=lambda _s: None,
        )
        assert limiter.wait_between_actions() == 5.0


class TestWhitelist:
    def test_normalize(self):
        assert normalize_username("  @Okan_Buruk ") == "okan_buruk"

    def test_contains_ignores_case_and_at(self):
        whitelist = Whitelist(["OkanBuruk", "@dostum"])
        assert whitelist.contains("okanburuk") is True
        assert "@DOSTUM" in whitelist
        assert whitelist.contains("yabanci") is False

    def test_from_file(self, tmp_path):
        path = tmp_path / "whitelist.txt"
        path.write_text("# yorum\n@dost1\ndost2\n", encoding="utf-8")
        whitelist = Whitelist.from_file(path)
        assert len(whitelist) == 2
        assert whitelist.contains("dost1")

    def test_missing_file_is_empty_not_error(self, tmp_path):
        whitelist = Whitelist.from_file(tmp_path / "yok.txt")
        assert len(whitelist) == 0
        assert whitelist.contains("kimse") is False

    def test_add_writes_to_file(self, tmp_path):
        path = tmp_path / "whitelist.txt"
        path.write_text("# baslik\n", encoding="utf-8")
        whitelist = Whitelist.from_file(path)
        assert whitelist.add("@yeni_dost") is True
        assert whitelist.add("yeni_dost") is False  # tekrar eklenmez
        content = path.read_text(encoding="utf-8")
        assert "yeni_dost" in content
        assert Whitelist.from_file(path).contains("yeni_dost") is True

    def test_add_many(self, tmp_path):
        path = tmp_path / "whitelist.txt"
        whitelist = Whitelist.from_file(path)
        assert whitelist.add_many(["a", "b", "a", "@b", "c"]) == 3
        assert len(whitelist) == 3
        assert path.read_text(encoding="utf-8").count("\n") == 3

    def test_empty_whitelist_is_truthy(self):
        """Bos beyaz liste 'yok' sayilmamali (kod 'if whitelist' yazsa bile)."""
        assert bool(Whitelist([])) is True


class TestRunLock:
    def test_acquire_and_release(self, tmp_path):
        path = tmp_path / "xbot.lock"
        with RunLock(path) as lock:
            assert path.exists()
            assert lock.acquired is True
        assert not path.exists()

    def test_second_run_is_refused(self, tmp_path):
        path = tmp_path / "xbot.lock"
        with RunLock(path):
            with pytest.raises(LockError, match="Başka bir XBot çalışması"):
                RunLock(path).acquire()

    def test_stale_lock_by_dead_pid_is_cleaned(self, tmp_path):
        path = tmp_path / "xbot.lock"
        path.write_text(
            json.dumps(
                {
                    "pid": 999999999,  # olmayan surec
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        with RunLock(path) as lock:
            assert lock.acquired is True

    def test_stale_lock_by_age_is_cleaned(self, tmp_path):
        path = tmp_path / "xbot.lock"
        old = datetime.now(timezone.utc) - timedelta(hours=5)
        path.write_text(
            json.dumps({"pid": os.getpid(), "started_at": old.isoformat()}),
            encoding="utf-8",
        )
        with RunLock(path, stale_hours=3) as lock:
            assert lock.acquired is True

    def test_broken_lock_file_is_cleaned(self, tmp_path):
        path = tmp_path / "xbot.lock"
        path.write_text("bozuk içerik", encoding="utf-8")
        with RunLock(path) as lock:
            assert lock.acquired is True

    def test_release_is_safe_when_not_acquired(self, tmp_path):
        RunLock(tmp_path / "xbot.lock").release()  # hata vermemeli

    def test_pid_alive_for_current_process(self):
        assert pid_alive(os.getpid()) is True
        assert pid_alive(999999999) is False
        assert pid_alive(0) is False
