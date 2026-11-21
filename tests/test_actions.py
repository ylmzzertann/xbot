"""Engelleme aksiyonu testleri (tarayici olmadan, sahte DOM ile)."""

from __future__ import annotations

import pytest

from xbot import selectors
from xbot.actions import (
    STATUS_ALREADY,
    STATUS_BLOCKED,
    STATUS_DRY_RUN,
    STATUS_LIMIT,
    STATUS_WHITELISTED,
    Blocker,
    PlaywrightBlockUi,
)
from xbot.errors import ActionFailed, SelectorNotFound
from xbot.models import Decision, Level, Match, Severity, Tweet
from xbot.ratelimit import LimitStatus

from fakes import FakeNode, FakePage, FakeSession

TWEET = Tweet(tweet_id="123", username="kotu_hesap", text="siktir git")
DECISION = Decision(
    tweet=TWEET,
    level=Level.HIGH,
    matches=(Match("profanity", "siktir", Severity.STRONG, "siktir"),),
    reasons=("güçlü eşleşme 'siktir'", "Açık küfür → YÜKSEK."),
)


# --------------------------------------------------------------------------
# sahte isbirlikcileri
# --------------------------------------------------------------------------


class FakeUi:
    """BlockUi arayuzunu taklit eder; adimlari kaydeder."""

    def __init__(self, *, verify: bool = True) -> None:
        self.steps: list[str] = []
        self.urls: list[str | None] = []
        self.verify = verify

    def open_tweet_menu(self, tweet_id: str, url: str | None = None) -> None:
        self.steps.append(f"menu:{tweet_id}")
        self.urls.append(url)

    def click_block(self) -> None:
        self.steps.append("engelle")

    def confirm_block(self) -> None:
        self.steps.append("onay")

    def verify_blocked(self, username: str) -> bool:
        self.steps.append(f"dogrula:{username}")
        return self.verify

    def close_menu(self) -> None:
        self.steps.append("kapat")


class FakeStorage:
    def __init__(self, *, blocked: set[str] | None = None) -> None:
        self.blocked = {b.lower() for b in (blocked or set())}
        self.records: list[tuple[Tweet, str]] = []
        self.rules: list[str | None] = []

    def is_blocked(self, username: str) -> bool:
        return username.lower() in self.blocked

    def record_block(self, tweet, decision, *, mode="auto", note="", rules=None) -> int:
        self.records.append((tweet, mode))
        self.rules.append(rules)
        return len(self.records)


class FakeWhitelist:
    def __init__(self, names: set[str] | None = None) -> None:
        self.names = {n.lower() for n in (names or set())}

    def contains(self, username: str) -> bool:
        return username.lower() in self.names


class FakeLimiter:
    def __init__(self, *, allowed: bool = True, reason: str = "uygun") -> None:
        self._status = LimitStatus(allowed, reason, 0, 0, 10, 40)
        self.registered = 0
        self.waits = 0

    def status(self) -> LimitStatus:
        return self._status

    def register_block(self) -> None:
        self.registered += 1

    def wait_between_actions(self) -> float:
        self.waits += 1
        return 0.0


def make_blocker(*, dry_run=False, ui=None, storage=None, whitelist=None, limiter=None):
    return Blocker(
        ui if ui is not None else FakeUi(),
        storage=storage if storage is not None else FakeStorage(),
        whitelist=whitelist if whitelist is not None else FakeWhitelist(),
        limiter=limiter if limiter is not None else FakeLimiter(),
        dry_run=dry_run,
    )


# --------------------------------------------------------------------------
# Blocker kurallari
# --------------------------------------------------------------------------


class TestBlockerRules:
    def test_dry_run_does_not_touch_ui(self):
        ui = FakeUi()
        outcome = make_blocker(dry_run=True, ui=ui).block(TWEET, DECISION)
        assert outcome.status == STATUS_DRY_RUN
        assert outcome.would_block is True
        assert ui.steps == []
        assert "ENGELLENİRDİ" in outcome.message

    def test_whitelisted_account_is_never_blocked(self):
        ui = FakeUi()
        blocker = make_blocker(ui=ui, whitelist=FakeWhitelist({"kotu_hesap"}))
        outcome = blocker.block(TWEET, DECISION)
        assert outcome.status == STATUS_WHITELISTED
        assert ui.steps == []
        assert "beyaz listede" in outcome.message

    def test_whitelist_checked_before_limits(self):
        """Beyaz liste, limit dolu olsa bile once bakilir."""
        blocker = make_blocker(
            whitelist=FakeWhitelist({"kotu_hesap"}),
            limiter=FakeLimiter(allowed=False, reason="limit"),
        )
        assert blocker.block(TWEET, DECISION).status == STATUS_WHITELISTED

    def test_already_blocked_account_is_skipped(self):
        ui = FakeUi()
        blocker = make_blocker(ui=ui, storage=FakeStorage(blocked={"kotu_hesap"}))
        outcome = blocker.block(TWEET, DECISION)
        assert outcome.status == STATUS_ALREADY
        assert ui.steps == []

    def test_limit_stops_blocking(self):
        ui = FakeUi()
        blocker = make_blocker(
            ui=ui, limiter=FakeLimiter(allowed=False, reason="Saatlik sınır doldu")
        )
        outcome = blocker.block(TWEET, DECISION)
        assert outcome.status == STATUS_LIMIT
        assert outcome.message == "Saatlik sınır doldu"
        assert ui.steps == []

    def test_successful_block_flow(self):
        ui = FakeUi()
        storage = FakeStorage()
        limiter = FakeLimiter()
        outcome = make_blocker(ui=ui, storage=storage, limiter=limiter).block(
            TWEET, DECISION
        )
        assert outcome.status == STATUS_BLOCKED
        assert outcome.blocked is True
        assert ui.steps == ["menu:123", "engelle", "onay", "dogrula:kotu_hesap"]
        assert storage.records[0][0] is TWEET
        assert limiter.registered == 1
        assert limiter.waits == 1  # islemler arasi bekleme
        assert outcome.record_id == 1

    def test_mode_is_recorded(self):
        storage = FakeStorage()
        make_blocker(storage=storage).block(TWEET, DECISION, mode="review")
        assert storage.records[0][1] == "review"

    def test_unverified_block_stops_the_run(self):
        ui = FakeUi(verify=False)
        storage = FakeStorage()
        with pytest.raises(ActionFailed, match="doğrulanamadı"):
            make_blocker(ui=ui, storage=storage).block(TWEET, DECISION)
        assert storage.records == []  # dogrulanmayan engelleme kaydedilmez
        assert ui.steps[-1] == "kapat"

    def test_no_ui_in_real_mode_is_an_error(self):
        blocker = Blocker(
            None,
            storage=FakeStorage(),
            whitelist=FakeWhitelist(),
            limiter=FakeLimiter(),
            dry_run=False,
        )
        with pytest.raises(ActionFailed):
            blocker.block(TWEET, DECISION)


# --------------------------------------------------------------------------
# PlaywrightBlockUi (sahte sayfa ile)
# --------------------------------------------------------------------------


def make_block_page(
    *,
    tweet_id: str = "123",
    with_tweet: bool = True,
    with_menu_item: bool = True,
    with_confirm: bool = True,
    confirm_stays: bool = False,
) -> tuple[FakePage, dict[str, FakeNode]]:
    """Engelleme akisini taklit eden sahte sayfa kurar."""
    menu_button = FakeNode()
    article = FakeNode({selectors.TWEET_MENU_BUTTON: [menu_button]})
    block_item = FakeNode(text="Engelle")
    dropdown = FakeNode(
        {selectors.MENU_BLOCK: [block_item] if with_menu_item else []}
    )
    confirm_button = FakeNode(text="Engelle")

    nodes: dict[str, list[FakeNode]] = {
        selectors.DROPDOWN: [dropdown],
        selectors.CONFIRM_SHEET: [FakeNode()],
    }
    if with_tweet:
        nodes[selectors.tweet_by_id(tweet_id)] = [article]
    if with_confirm:
        nodes[selectors.CONFIRM_BUTTON] = [confirm_button]

    hidden = set() if confirm_stays else {selectors.CONFIRM_SHEET}
    page = FakePage(nodes=nodes, hidden=hidden)
    return page, {
        "article": article,
        "menu_button": menu_button,
        "block_item": block_item,
        "confirm_button": confirm_button,
    }


class TestPlaywrightBlockUi:
    def test_full_flow_clicks_every_step(self):
        page, parts = make_block_page()
        ui = PlaywrightBlockUi(page)
        ui.open_tweet_menu("123")
        ui.click_block()
        ui.confirm_block()
        assert ui.verify_blocked("kotu_hesap") is True
        assert parts["menu_button"].clicks == 1
        assert parts["block_item"].clicks == 1
        assert parts["confirm_button"].clicks == 1
        assert parts["article"].scrolled == 1

    def test_missing_tweet_raises_with_evidence(self):
        page, _ = make_block_page(with_tweet=False)
        session = FakeSession()
        ui = PlaywrightBlockUi(page, session=session)
        with pytest.raises(SelectorNotFound, match="engellenecek tweet"):
            ui.open_tweet_menu("123")
        assert session.saved  # ekran goruntusu + HTML kaydedildi

    def test_missing_block_menu_item_raises(self):
        page, _ = make_block_page(with_menu_item=False)
        ui = PlaywrightBlockUi(page)
        ui.open_tweet_menu("123")
        with pytest.raises(SelectorNotFound, match="Engelle"):
            ui.click_block()

    def test_missing_confirm_button_raises(self):
        """Onay penceresi acilir ama 'Engelle' dugmesi bulunamazsa durur."""
        page, _ = make_block_page(with_confirm=False)
        ui = PlaywrightBlockUi(page)
        ui.open_tweet_menu("123")
        ui.click_block()
        with pytest.raises(SelectorNotFound, match="onay penceresindeki"):
            ui.confirm_block()

    def test_verify_fails_when_dialog_stays_open(self):
        page, _ = make_block_page(confirm_stays=True)
        ui = PlaywrightBlockUi(page)
        assert ui.verify_blocked("kotu_hesap") is False

    def test_close_menu_presses_escape(self):
        page, _ = make_block_page()
        PlaywrightBlockUi(page).close_menu()
        assert page.keyboard.presses == ["Escape"]

    def test_unexpected_page_stops_before_blocking(self):
        page, _ = make_block_page()
        page.body = "Hesabınız kısıtlandı"
        ui = PlaywrightBlockUi(page, session=FakeSession())
        from xbot.errors import SafetyStop

        with pytest.raises(SafetyStop):
            ui.open_tweet_menu("123")
