"""'phrase' ozelligi: kullanicinin yazdigi ifadeyle arama, onay ve tweet dosyasi."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from xbot import selectors
from xbot.actions import (
    STATUS_BLOCKED,
    STATUS_DRY_RUN,
    STATUS_LIMIT,
    STATUS_NOT_FOUND,
    STATUS_WHITELISTED,
    Blocker,
    PlaywrightBlockUi,
)
from xbot.detector.phrase import (
    PhraseDetector,
    is_short_phrase,
    rule_label,
    validate_phrase,
)
from xbot.errors import SafetyStop
from xbot.evidence import HEADERS, BlockedTweetLog
from xbot.models import Decision, Level, Tweet
from xbot.phrase_hunt import (
    STATUS_ALREADY,
    STATUS_SELF,
    STATUS_TO_BLOCK,
    STATUS_WHITELISTED as CAND_WHITELISTED,
    build_candidates,
    match_tweets,
    parse_numbers,
    plan_blocks,
    search_query_for,
)
from xbot.ratelimit import LimitStatus
from xbot.safety import NOT_FOUND, classify_page
from xbot.storage import Storage
from xbot.whitelist import Whitelist

from fakes import FakeNode, FakePage, FakeSession

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def tweet(tweet_id: str, username: str, text: str) -> Tweet:
    return Tweet(tweet_id=tweet_id, username=username, text=text, created_at=NOW)


# --------------------------------------------------------------------------
# ifade dogrulama ve eslestirme
# --------------------------------------------------------------------------


class TestValidatePhrase:
    def test_spaces_are_collapsed(self):
        assert validate_phrase("  okan    istifa ") == "okan istifa"

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_empty_is_rejected(self, value):
        with pytest.raises(ValueError, match="kelime ya da cümle"):
            validate_phrase(value)

    @pytest.mark.parametrize("value", ["a", "!!", "1"])
    def test_too_short_is_rejected(self, value):
        with pytest.raises(ValueError, match="çok kısa"):
            validate_phrase(value)

    def test_short_phrase_warning(self):
        assert is_short_phrase("ok") is True
        assert is_short_phrase("okan istifa") is False


class TestPhraseDetector:
    @pytest.mark.parametrize(
        "text",
        [
            "Okan istifa artık",
            "OKAN İSTİFA!!!",
            "okan istifaaa",
            "#OkanIstifa",
            "o.k.a.n istifa",
            "bence okan istifa etmeli",
        ],
    )
    def test_multiword_variants_match(self, text):
        assert PhraseDetector(["okan istifa"]).matches(tweet("1", "u", text)) is True

    @pytest.mark.parametrize(
        "text",
        ["istifa etsin okan", "okanın istifası", "bugün okan harikaydı", "istifa"],
    )
    def test_non_matching(self, text):
        assert PhraseDetector(["okan istifa"]).matches(tweet("1", "u", text)) is False

    def test_single_word_matches_inside_words_by_default(self):
        detector = PhraseDetector(["hakem"])
        assert detector.matches(tweet("1", "u", "hakemler rezil")) is True
        assert detector.matches(tweet("1", "u", "haklı")) is False

    def test_whole_word_option(self):
        detector = PhraseDetector(["hakem"], whole_word=True)
        assert detector.matches(tweet("1", "u", "HAKEM kim")) is True
        assert detector.matches(tweet("1", "u", "hakemler rezil")) is False

    def test_whole_word_is_ignored_for_multiword(self):
        detector = PhraseDetector(["okan istifa"], whole_word=True)
        assert detector.matches(tweet("1", "u", "okan istifa")) is True

    def test_verdict_contents(self):
        verdict = PhraseDetector(["okan istifa"]).analyze(tweet("1", "u", "okan istifa"))
        assert verdict.level is Level.HIGH
        assert verdict.matches[0].rule == rule_label("okan istifa") == 'ifade: "okan istifa"'
        assert "Aranan ifade bulundu" in verdict.reasons[0]

    def test_empty_detector_is_clean(self):
        assert PhraseDetector([]).analyze(tweet("1", "u", "her şey")).level is Level.CLEAN

    def test_detector_is_registered_as_plugin(self):
        from xbot.detector.base import build_detector

        detector = build_detector("phrase", phrases=["okan"])
        assert detector.matches(tweet("1", "u", "OKAN"))


class TestSearchQuery:
    def test_single_word_plain(self):
        assert search_query_for("hakem") == "hakem"

    def test_multiword_is_quoted(self):
        assert search_query_for("okan   istifa") == '"okan istifa"'

    def test_user_quotes_are_not_doubled(self):
        assert search_query_for('"okan istifa"') == '"okan istifa"'


# --------------------------------------------------------------------------
# adaylar, secim ve plan
# --------------------------------------------------------------------------

TWEETS = [
    tweet("1", "kizgin1", "Okan istifa artık yeter"),
    tweet("2", "Kizgin2", "OKAN İSTİFA!!! siktir git"),
    tweet("3", "kizgin2", "okan istifa diyorum hala"),
    tweet("4", "dostum", "okan istifa etsin bence"),
    tweet("5", "benim_hesap", "okan istifa mı?"),
    tweet("6", "alakasiz", "bugün maç var"),
]


class FakeStorage:
    def __init__(self, blocked=()):
        self.blocked = {b.lower() for b in blocked}

    def is_blocked(self, username):
        return username.lower() in self.blocked


class TestMatchTweets:
    def test_only_real_matches_are_kept(self):
        matches = match_tweets(TWEETS, PhraseDetector(["okan istifa"]))
        assert [t.tweet_id for t, _ in matches] == ["1", "2", "3", "4", "5"]
        decision = matches[0][1]
        assert decision.level is Level.HIGH
        assert decision.rule_summary == 'ifade: "okan istifa"'


class TestBuildCandidates:
    @pytest.fixture
    def candidates(self, engine):
        matches = match_tweets(TWEETS, PhraseDetector(["okan istifa"]))
        return build_candidates(
            matches,
            whitelist=Whitelist(["dostum"]),
            storage=FakeStorage(),
            own_handle="@Benim_Hesap",
            engine=engine,
        )

    def test_grouped_by_user_case_insensitive(self, candidates):
        assert [c.username for c in candidates] == [
            "kizgin1",
            "Kizgin2",
            "dostum",
            "benim_hesap",
        ]
        assert [c.number for c in candidates] == [1, 2, 3, 4]
        assert len(candidates[1].tweets) == 2  # ayni hesabin iki tweeti

    def test_statuses(self, candidates):
        statuses = [c.status for c in candidates]
        assert statuses == [STATUS_TO_BLOCK, STATUS_TO_BLOCK, CAND_WHITELISTED, STATUS_SELF]
        assert candidates[2].will_block is False
        assert "beyaz listede" in candidates[2].status_label

    def test_already_blocked(self):
        matches = match_tweets(TWEETS[:1], PhraseDetector(["okan istifa"]))
        (candidate,) = build_candidates(matches, storage=FakeStorage(blocked=["KIZGIN1"]))
        assert candidate.status == STATUS_ALREADY

    def test_profanity_level_is_highest_of_users_tweets(self, candidates):
        assert candidates[0].profanity is Level.CLEAN
        assert candidates[1].profanity is Level.HIGH  # "siktir git"


class TestParseNumbers:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("2", {2}),
            ("2,5", {2, 5}),
            ("2, 5 ,7-9", {2, 5, 7, 8, 9}),
            ("9-7", {7, 8, 9}),
            ("1 3", {1, 3}),
            ("", set()),
        ],
    )
    def test_valid(self, text, expected):
        assert parse_numbers(text, 10) == expected

    @pytest.mark.parametrize("text", ["iki", "2-x", "0", "11", "3-12"])
    def test_invalid(self, text):
        with pytest.raises(ValueError):
            parse_numbers(text, 10)


class TestPlanBlocks:
    @pytest.fixture
    def candidates(self):
        matches = match_tweets(TWEETS, PhraseDetector(["okan istifa"]))
        return build_candidates(
            matches, whitelist=Whitelist(["dostum"]), own_handle="benim_hesap"
        )

    def test_plan_without_limit(self, candidates):
        plan = plan_blocks(candidates)
        assert [c.username for c in plan.to_block] == ["kizgin1", "Kizgin2"]
        assert len(plan.skipped) == 2

    def test_excluded_numbers(self, candidates):
        plan = plan_blocks(candidates, excluded={1})
        assert [c.username for c in plan.to_block] == ["Kizgin2"]
        assert [c.username for c in plan.excluded] == ["kizgin1"]

    def test_limit_defers_the_rest(self, candidates):
        plan = plan_blocks(candidates, limit_left=1)
        assert [c.username for c in plan.to_block] == ["kizgin1"]
        assert [c.username for c in plan.deferred] == ["Kizgin2"]

    def test_zero_limit_defers_everything(self, candidates):
        plan = plan_blocks(candidates, limit_left=0)
        assert plan.to_block == []
        assert len(plan.deferred) == 2


# --------------------------------------------------------------------------
# engellenenlerin tweet dosyasi
# --------------------------------------------------------------------------


class TestBlockedTweetLog:
    def test_new_file_has_bom_and_header(self, tmp_path):
        log = BlockedTweetLog(tmp_path / "kayit" / "tweetler.csv")
        assert log.append([tweet("1", "kotu", "siktir git")], reason="siktir", mode="auto") == 1
        raw = log.path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        first_line = raw.decode("utf-8-sig").splitlines()[0]
        assert first_line == ";".join(HEADERS)

    def test_appending_keeps_old_rows_and_single_header(self, tmp_path):
        log = BlockedTweetLog(tmp_path / "tweetler.csv")
        log.append([tweet("1", "a", "birinci")], reason="r1", mode="auto")
        log.append([tweet("2", "b", "ikinci"), tweet("3", "b", "üçüncü")], reason="r2", mode="phrase")
        rows = log.read()
        assert [row["tweet_metni"] for row in rows] == ["birinci", "ikinci", "üçüncü"]
        assert log.path.read_bytes().count(b"\xef\xbb\xbf") == 1
        assert log.path.read_text(encoding="utf-8-sig").count("kayit_zamani") == 1
        assert rows[1]["sebep"] == "r2"
        assert rows[1]["mod"] == "phrase"
        assert rows[1]["tweet_linki"] == "https://x.com/b/status/2"
        assert rows[1]["tweet_zamani"]  # yerel saatle yazildi

    def test_multiline_and_semicolon_text_survive(self, tmp_path):
        log = BlockedTweetLog(tmp_path / "tweetler.csv")
        text = "satır bir; noktalı virgül\nsatır iki \"tırnak\""
        log.append([tweet("1", "a", text)], reason="x", mode="auto")
        assert log.read()[0]["tweet_metni"] == text

    def test_empty_append_writes_nothing(self, tmp_path):
        log = BlockedTweetLog(tmp_path / "tweetler.csv")
        assert log.append([], reason="x") == 0
        assert not log.path.exists()
        assert log.read() == []
        assert log.count() == 0


# --------------------------------------------------------------------------
# Blocker: dosyaya yazma ve silinmis tweet
# --------------------------------------------------------------------------


class RecordingUi:
    def __init__(self, *, verify=True, raise_on_open=None):
        self.opened: list[tuple[str, str | None]] = []
        self.verify = verify
        self.raise_on_open = raise_on_open

    def open_tweet_menu(self, tweet_id, url=None):
        self.opened.append((tweet_id, url))
        if self.raise_on_open is not None:
            raise self.raise_on_open

    def click_block(self):
        pass

    def confirm_block(self):
        pass

    def verify_blocked(self, username):
        return self.verify

    def close_menu(self):
        pass


class OpenLimiter:
    def __init__(self, allowed=True):
        self._status = LimitStatus(allowed, "limit doldu" if not allowed else "uygun", 0, 0, 10, 40)

    def status(self):
        return self._status

    def register_block(self):
        pass

    def wait_between_actions(self):
        return 0.0


def phrase_decision(tw: Tweet) -> Decision:
    return match_tweets([tw], PhraseDetector(["okan istifa"]))[0][1]


@pytest.fixture
def db(tmp_path):
    with Storage(tmp_path / "db.sqlite3") as storage:
        yield storage


class TestBlockerWritesTweetLog:
    def test_success_writes_all_evidence_tweets(self, tmp_path, db):
        log = BlockedTweetLog(tmp_path / "tweetler.csv")
        first = tweet("2", "kizgin2", "OKAN İSTİFA!!!")
        second = tweet("3", "kizgin2", "okan istifa diyorum")
        blocker = Blocker(
            RecordingUi(), storage=db, whitelist=Whitelist([]), limiter=OpenLimiter(),
            dry_run=False, tweet_log=log,
        )
        outcome = blocker.block(
            first, phrase_decision(first), mode="phrase",
            evidence_tweets=[first, second], reason='ifade: "okan istifa"',
        )
        assert outcome.status == STATUS_BLOCKED
        rows = log.read()
        assert [row["tweet_id"] for row in rows] == ["2", "3"]
        assert all(row["sebep"] == 'ifade: "okan istifa"' for row in rows)
        assert all(row["mod"] == "phrase" for row in rows)
        record = db.recent_blocks(1)[0]
        assert record.rules == 'ifade: "okan istifa"'
        assert record.mode == "phrase"

    def test_ui_gets_tweet_url_for_navigation(self, tmp_path, db):
        ui = RecordingUi()
        tw = tweet("9", "kotu", "okan istifa")
        Blocker(ui, storage=db, whitelist=Whitelist([]), limiter=OpenLimiter(), dry_run=False).block(
            tw, phrase_decision(tw)
        )
        assert ui.opened == [("9", "https://x.com/kotu/status/9")]

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({"dry_run": True}, STATUS_DRY_RUN),
            ({"whitelist": Whitelist(["kotu"])}, STATUS_WHITELISTED),
            ({"limiter": OpenLimiter(allowed=False)}, STATUS_LIMIT),
        ],
    )
    def test_nothing_written_when_not_blocked(self, tmp_path, db, kwargs, expected):
        log = BlockedTweetLog(tmp_path / "tweetler.csv")
        params = dict(storage=db, whitelist=Whitelist([]), limiter=OpenLimiter(),
                      dry_run=False, tweet_log=log)
        params.update(kwargs)
        tw = tweet("1", "kotu", "okan istifa")
        outcome = Blocker(RecordingUi(), **params).block(tw, phrase_decision(tw))
        assert outcome.status == expected
        assert log.read() == []

    def test_file_error_does_not_undo_block(self, tmp_path, db):
        class BrokenLog:
            def append(self, *_args, **_kwargs):
                raise OSError("disk dolu")

        tw = tweet("1", "kotu", "okan istifa")
        outcome = Blocker(
            RecordingUi(), storage=db, whitelist=Whitelist([]), limiter=OpenLimiter(),
            dry_run=False, tweet_log=BrokenLog(),
        ).block(tw, phrase_decision(tw))
        assert outcome.status == STATUS_BLOCKED
        assert db.is_blocked("kotu") is True


class TestDeletedTweet:
    def test_not_found_page_is_classified(self):
        state = classify_page("https://x.com/a/status/1", "Hmm...this page doesn't exist.")
        assert state.kind == NOT_FOUND
        turkish = classify_page("https://x.com/a/status/1", "Hmm... bu sayfa mevcut değil.")
        assert turkish.kind == NOT_FOUND

    def test_deleted_tweet_skips_only_that_account(self, db):
        ui = RecordingUi(raise_on_open=SafetyStop("yok", kind=NOT_FOUND))
        tw = tweet("1", "silen", "okan istifa")
        outcome = Blocker(
            ui, storage=db, whitelist=Whitelist([]), limiter=OpenLimiter(), dry_run=False
        ).block(tw, phrase_decision(tw))
        assert outcome.status == STATUS_NOT_FOUND
        assert "silinmiş" in outcome.message
        assert db.is_blocked("silen") is False

    def test_other_safety_stops_still_stop(self, db):
        ui = RecordingUi(raise_on_open=SafetyStop("captcha", kind="captcha"))
        tw = tweet("1", "x", "okan istifa")
        blocker = Blocker(
            ui, storage=db, whitelist=Whitelist([]), limiter=OpenLimiter(), dry_run=False
        )
        with pytest.raises(SafetyStop):
            blocker.block(tw, phrase_decision(tw))


class TestNavigationFallback:
    """Tweet sayfada yoksa kendi sayfasina gidilir (X eski tweetleri DOM'dan siler)."""

    def test_goes_to_tweet_page_when_not_in_dom(self):
        menu_button = FakeNode()
        article = FakeNode({selectors.TWEET_MENU_BUTTON: [menu_button]})
        page = FakePage(nodes={selectors.DROPDOWN: [FakeNode()]})

        class NavSession(FakeSession):
            def __init__(self):
                super().__init__()
                self.visited: list[str] = []

            def goto(self, url, *, context=""):
                self.visited.append(url)
                page.nodes[selectors.tweet_by_id("77")] = [article]
                page.visible.add(selectors.tweet_by_id("77"))

        session = NavSession()
        ui = PlaywrightBlockUi(page, session=session, timeout_ms=1000)
        ui.open_tweet_menu("77", url="https://x.com/kotu/status/77")
        assert session.visited == ["https://x.com/kotu/status/77"]
        assert menu_button.clicks == 1

    def test_no_navigation_when_tweet_is_on_page(self):
        article = FakeNode({selectors.TWEET_MENU_BUTTON: [FakeNode()]})
        page = FakePage(
            nodes={selectors.tweet_by_id("5"): [article], selectors.DROPDOWN: [FakeNode()]}
        )

        class NavSession(FakeSession):
            visited: list[str] = []

            def goto(self, url, *, context=""):  # pragma: no cover - cagrilmamali
                self.visited.append(url)

        session = NavSession()
        PlaywrightBlockUi(page, session=session).open_tweet_menu("5", url="https://x.com/a/status/5")
        assert session.visited == []


class TestStorageRulesOverride:
    def test_rules_label_is_stored(self, db):
        tw = tweet("1", "kotu", "okan istifa")
        db.record_block(tw, phrase_decision(tw), mode="phrase", rules="özel etiket")
        assert db.recent_blocks(1)[0].rules == "özel etiket"

    def test_default_rules_come_from_decision(self, db):
        tw = tweet("1", "kotu", "okan istifa")
        db.record_block(tw, phrase_decision(tw))
        assert db.recent_blocks(1)[0].rules == 'ifade: "okan istifa"'
