"""GERCEK Playwright ile uctan uca testler (X'e baglanmadan).

Yerel bir HTML dosyasi X arayuzunu taklit eder: ayni data-testid'ler, ayni
"..." menusu -> Engelle -> onay akisi. Boylece tarayici tarafi (oturum acma,
seciciler, kaydirma, tiklama, dogrulama, kanit kaydi) gercek tarayicida test
edilir; X hesabina hicbir istek gitmez.

Playwright kurulu degilse bu dosya tamamen atlanir.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from xbot.actions import Blocker, PlaywrightBlockUi
from xbot.browser import BrowserSession, require_first
from xbot.config import AppConfig
from xbot.errors import ActionFailed, SafetyStop, SelectorNotFound
from xbot.models import Decision, Level, Match, Severity, Tweet
from xbot.ratelimit import RateLimiter
from xbot.scraper import PlaywrightTweetSource, SearchScraper
from xbot.storage import Storage
from xbot.timefilter import TimeWindow
from xbot.whitelist import Whitelist
from xbot import selectors

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None,
    reason="Playwright kurulu değil (python -m pip install playwright)",
)

NOW = datetime.now(timezone.utc)


def stamp(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


TWEETS = [
    {"user": "kotu_hesap", "id": "111", "text": "siktir git buradan", "min": 5},
    {"user": "iyi_hesap", "id": "222", "text": "ne güzel maçtı", "min": 12},
    {"user": "belirsiz", "id": "333", "text": "amk gol", "min": 30},
]


def build_mock_html(tweets=TWEETS, *, logged_in: bool = True, empty: bool = False) -> str:
    """X arama sayfasinin kucuk bir taklidini uretir."""
    articles = []
    for item in tweets:
        articles.append(
            f"""
    <article data-testid="tweet">
      <div data-testid="User-Name">Ad Soyad<br>@{item["user"]}</div>
      <div data-testid="tweetText">{item["text"]}</div>
      <a href="/{item["user"]}/status/{item["id"]}" role="link">
        <time datetime="{stamp(item["min"])}">{int(item["min"])} dk</time>
      </a>
      <button data-testid="caret" data-user="{item["user"]}"
              onclick="openMenu(this.dataset.user)">...</button>
    </article>"""
        )
    nav = (
        '<div data-testid="SideNav_AccountSwitcher_Button">Benim Hesabım @benim_hesap</div>'
        if logged_in
        else ""
    )
    body = (
        '<div data-testid="empty_state_header_text">Sonuç bulunamadı</div>'
        if empty
        else "".join(articles)
    )
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"><title>Arama / X</title>
<style>#menu,#confirm{{display:none}} article{{min-height:220px}}</style>
</head><body>
  {nav}
  <div data-testid="primaryColumn">{body}</div>

  <div id="menu" data-testid="Dropdown" role="menu">
    <div role="menuitem" data-testid="mute">Sessize al</div>
    <div role="menuitem" data-testid="block" onclick="openConfirm()">Engelle</div>
  </div>

  <div id="confirm" data-testid="confirmationSheetDialog" role="dialog">
    <div>Engellemek istediğine emin misin?</div>
    <button data-testid="confirmationSheetConfirm" onclick="doBlock()">Engelle</button>
    <button data-testid="confirmationSheetCancel">Vazgeç</button>
  </div>

<script>
  window.__blocked = [];
  let current = null;
  function openMenu(user) {{ current = user; document.getElementById('menu').style.display = 'block'; }}
  function openConfirm() {{
    document.getElementById('menu').style.display = 'none';
    document.getElementById('confirm').style.display = 'block';
  }}
  function doBlock() {{
    document.getElementById('confirm').style.display = 'none';
    window.__blocked.push(current);
  }}
</script>
</body></html>
"""


@pytest.fixture(scope="module")
def pages(tmp_path_factory) -> dict[str, str]:
    """Taklit sayfalari dosyaya yazar ve file:// adreslerini dondurur."""
    directory = tmp_path_factory.mktemp("sahte_x")
    written = {}
    for name, html in (
        ("arama", build_mock_html()),
        ("bos", build_mock_html(empty=True)),
        ("kisitli", "<html lang='tr'><head><title>X</title></head>"
                    "<body>Hesabınız kısıtlandı</body></html>"),
        ("bozuk", "<html lang='tr'><head><title>Arama / X</title></head>"
                  "<body><div data-testid='primaryColumn'>arayüz değişti</div></body></html>"),
        ("durum", build_mock_html(
            [{"user": "uzak_hesap", "id": "555", "text": "okan istifa etsin", "min": 3}]
        )),
        ("silinmis", "<html lang='tr'><head><title>X</title></head><body>"
                     "Hmm...this page doesn't exist. Try searching for something else."
                     "</body></html>"),
    ):
        path = directory / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        written[name] = path.as_uri()
    return written


@pytest.fixture(scope="module")
def config(tmp_path_factory, project_root) -> AppConfig:
    base = tmp_path_factory.mktemp("xbot_entegrasyon")
    return AppConfig.from_dict(
        {
            "search_queries": ["deneme"],
            "target_names": ["okan"],
            "headless": True,
            "delays": {"between_actions": [0, 0], "between_scrolls": [0, 0]},
            "browser": {"timeout_seconds": 15},
            "paths": {
                "profile_dir": str(base / "profil"),
                "db_path": str(base / "veri.sqlite3"),
                "log_dir": str(base / "kayit"),
                "screenshot_dir": str(base / "kayit" / "ekran"),
                "report_dir": str(base / "rapor"),
            },
            "files": {
                "profanity": str(project_root / "data" / "profanity.txt"),
                "allowlist_words": str(project_root / "data" / "allowlist_words.txt"),
                "allowlist_phrases": str(project_root / "data" / "allowlist_phrases.txt"),
                "positive_context": str(project_root / "data" / "positive_context.txt"),
                "whitelist": str(base / "whitelist.txt"),
            },
        },
        base_dir=base,
    )


@pytest.fixture(scope="module")
def session(config) -> BrowserSession:
    """Gercek (headless) tarayici oturumu — modul boyunca tek kez acilir."""
    config.ensure_dirs()
    browser = BrowserSession(config, headless=True)
    browser.start()
    yield browser
    browser.stop()


# --------------------------------------------------------------------------
# oturum ve sayfa durumu
# --------------------------------------------------------------------------


class TestSession:
    def test_browser_opens_with_persistent_profile(self, session, config):
        assert session.is_open is True
        assert Path(config.paths.profile_dir).exists()

    def test_goto_and_login_detection(self, session, pages):
        session.goto(pages["arama"])
        assert session.is_logged_in() is True
        assert session.detect_handle() == "benim_hesap"

    def test_restricted_page_stops_the_program(self, session, pages, config):
        with pytest.raises(SafetyStop) as info:
            session.goto(pages["kisitli"])
        assert info.value.kind == "restricted"
        # kanit dosyalari gercekten yazildi mi?
        assert info.value.evidence
        for path in info.value.evidence:
            assert Path(path).exists()
        screenshots = list(Path(config.paths.screenshot_dir).glob("*.png"))
        assert screenshots

    def test_missing_selector_saves_html_and_screenshot(self, session, pages, config):
        session.goto(pages["bozuk"])
        with pytest.raises(SelectorNotFound) as info:
            require_first(
                session.page,
                selectors.CHAINS["tweet"],
                what="tweet kutusu",
                session=session,
            )
        assert info.value.evidence
        html_files = [p for p in info.value.evidence if str(p).endswith(".html")]
        assert html_files and Path(html_files[0]).exists()
        assert "arayüz değişti" in Path(html_files[0]).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# tarama
# --------------------------------------------------------------------------


class TestScrapingRealDom:
    def test_reads_every_field(self, session, pages):
        session.goto(pages["arama"])
        tweets = PlaywrightTweetSource(session.page, session=session).visible_tweets()
        assert [t.tweet_id for t in tweets] == ["111", "222", "333"]
        first = tweets[0]
        assert first.username == "kotu_hesap"
        assert first.text == "siktir git buradan"
        assert first.timestamp.startswith(stamp(5)[:16])
        assert first.url == "https://x.com/kotu_hesap/status/111"
        assert first.display_name == "Ad Soyad"

    def test_empty_results_page(self, session, pages):
        session.goto(pages["bos"])
        source = PlaywrightTweetSource(session.page, session=session)
        assert source.has_results() is False
        assert source.visible_tweets() == []

    def test_scraper_applies_time_window(self, session, pages):
        session.goto(pages["arama"])
        source = PlaywrightTweetSource(session.page, session=session)
        window = TimeWindow.last_minutes(20, reference=NOW)
        result = SearchScraper(source, max_scrolls=2).scrape("deneme", window)
        assert {t.tweet_id for t in result.tweets} == {"111", "222"}  # 30 dk'lik disarida
        assert result.too_old == 1

    def test_scrolling_works_on_real_page(self, session, pages):
        session.goto(pages["arama"])
        source = PlaywrightTweetSource(session.page, session=session)
        before = session.page.evaluate("window.scrollY")
        source.scroll_once()
        after = session.page.evaluate("window.scrollY")
        assert after >= before


# --------------------------------------------------------------------------
# engelleme akisi
# --------------------------------------------------------------------------


class TestBlockingRealDom:
    def test_full_block_flow(self, session, pages):
        session.goto(pages["arama"])
        ui = PlaywrightBlockUi(session.page, session=session, timeout_ms=5000)
        ui.open_tweet_menu("111")
        ui.click_block()
        ui.confirm_block()
        assert ui.verify_blocked("kotu_hesap") is True
        assert session.page.evaluate("window.__blocked") == ["kotu_hesap"]

    def test_menu_is_not_clicked_when_tweet_missing(self, session, pages):
        session.goto(pages["arama"])
        ui = PlaywrightBlockUi(session.page, session=session, timeout_ms=3000)
        with pytest.raises(SelectorNotFound, match="engellenecek tweet"):
            ui.open_tweet_menu("999999")

    def test_blocker_records_evidence_end_to_end(self, session, pages, config, tmp_path):
        session.goto(pages["arama"])
        tweet = Tweet(
            tweet_id="333",
            username="belirsiz",
            text="amk gol",
            created_at=NOW,
        )
        decision = Decision(
            tweet=tweet,
            level=Level.HIGH,
            matches=(Match("profanity", "amk", Severity.AMBIGUOUS, "amk"),),
            reasons=("belirsiz ifade + hedef isim → YÜKSEK.",),
        )
        with Storage(tmp_path / "engel.sqlite3") as storage:
            limiter = RateLimiter(
                config.limits, config.delays, storage=storage, sleeper=lambda _s: None
            )
            blocker = Blocker(
                PlaywrightBlockUi(session.page, session=session, timeout_ms=5000),
                storage=storage,
                whitelist=Whitelist([]),
                limiter=limiter,
                dry_run=False,
            )
            outcome = blocker.block(tweet, decision)
            assert outcome.blocked is True
            assert session.page.evaluate("window.__blocked")[-1] == "belirsiz"
            record = storage.recent_blocks(1)[0]
            assert record.username == "belirsiz"
            assert record.rules == "amk"
            assert record.url == "https://x.com/belirsiz/status/333"
            assert storage.is_blocked("belirsiz") is True

    def test_whitelisted_user_is_not_touched_in_real_browser(self, session, pages, config, tmp_path):
        session.goto(pages["arama"])
        tweet = Tweet(tweet_id="111", username="kotu_hesap", text="siktir git")
        decision = Decision(tweet=tweet, level=Level.HIGH)
        with Storage(tmp_path / "beyaz.sqlite3") as storage:
            blocker = Blocker(
                PlaywrightBlockUi(session.page, session=session),
                storage=storage,
                whitelist=Whitelist(["kotu_hesap"]),
                limiter=RateLimiter(config.limits, config.delays, storage=storage,
                                    sleeper=lambda _s: None),
                dry_run=False,
            )
            before = session.page.evaluate("window.__blocked.length")
            outcome = blocker.block(tweet, decision)
            assert outcome.status == "whitelisted"
            assert session.page.evaluate("window.__blocked.length") == before

    def test_click_failure_gives_turkish_error(self, session, pages):
        """Menu acilmadan Engelle satirina basilmaya calisilirsa anlasilir hata."""
        session.goto(pages["arama"])
        ui = PlaywrightBlockUi(session.page, session=session, timeout_ms=2000)
        with pytest.raises((ActionFailed, SelectorNotFound)) as info:
            ui.click_block()
        assert "menü" in str(info.value).lower() or "engelle" in str(info.value).lower()


# --------------------------------------------------------------------------
# phrase ozelligi icin: tweet sayfada yoksa kendi sayfasina gitme
# --------------------------------------------------------------------------


class TestNavigationAndDeletedTweets:
    def _blocker(self, session, config, storage, log):
        return Blocker(
            PlaywrightBlockUi(session.page, session=session, timeout_ms=5000),
            storage=storage,
            whitelist=Whitelist([]),
            limiter=RateLimiter(config.limits, config.delays, storage=storage,
                                sleeper=lambda _s: None),
            dry_run=False,
            tweet_log=log,
        )

    def test_goes_to_tweet_page_and_blocks(self, session, pages, config, tmp_path):
        from xbot.detector.phrase import PhraseDetector
        from xbot.evidence import BlockedTweetLog
        from xbot.phrase_hunt import match_tweets

        session.goto(pages["bos"])  # su anki sayfada bu tweet YOK
        tw = Tweet("555", "uzak_hesap", "okan istifa etsin", created_at=NOW,
                   url=pages["durum"])
        decision = match_tweets([tw], PhraseDetector(["okan istifa"]))[0][1]
        log = BlockedTweetLog(tmp_path / "tweetler.csv")
        with Storage(tmp_path / "nav.sqlite3") as storage:
            outcome = self._blocker(session, config, storage, log).block(
                tw, decision, mode="phrase", evidence_tweets=[tw],
                reason='ifade: "okan istifa"',
            )
            assert outcome.blocked is True
            assert storage.is_blocked("uzak_hesap") is True
        assert session.page.url == pages["durum"]
        assert session.page.evaluate("window.__blocked") == ["uzak_hesap"]
        rows = log.read()
        assert rows[0]["hesap"] == "uzak_hesap"
        assert rows[0]["tweet_metni"] == "okan istifa etsin"

    def test_deleted_tweet_is_skipped_not_stopped(self, session, pages, config, tmp_path):
        from xbot.actions import STATUS_NOT_FOUND

        session.goto(pages["bos"])
        tw = Tweet("666", "silen_hesap", "okan istifa", created_at=NOW,
                   url=pages["silinmis"])
        decision = Decision(tweet=tw, level=Level.HIGH)
        with Storage(tmp_path / "silinen.sqlite3") as storage:
            outcome = self._blocker(session, config, storage, None).block(tw, decision)
            assert outcome.status == STATUS_NOT_FOUND
            assert storage.is_blocked("silen_hesap") is False
