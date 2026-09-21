"""Secici dosyasi, secici yardimcilari ve bildirim testleri."""

from __future__ import annotations

import pytest

from xbot import selectors
from xbot.browser import find_first, require_first, wait_for_first
from xbot.errors import SelectorNotFound
from xbot.notify import ERROR_FILE_NAME, notify, write_error_file

from fakes import FakeNode, FakePage, FakeSession


class TestUrls:
    def test_search_url_uses_latest_tab(self):
        url = selectors.search_url("Okan Buruk")
        assert url.startswith("https://x.com/search?")
        assert "q=Okan%20Buruk" in url
        assert "f=live" in url  # "Son" sekmesi

    def test_search_url_without_latest(self):
        assert "f=live" not in selectors.search_url("test", latest=False)

    def test_turkish_characters_are_encoded(self):
        assert "%C3%BC" in selectors.search_url("küfür")  # ü

    def test_profile_and_status_urls(self):
        assert selectors.profile_url("@abc") == "https://x.com/abc"
        assert selectors.status_url("abc", "12") == "https://x.com/abc/status/12"
        assert selectors.following_url("abc") == "https://x.com/abc/following"

    def test_tweet_by_id_selector(self):
        selector = selectors.tweet_by_id("999")
        assert "999" in selector
        assert selector.startswith("article")
        assert len(selectors.tweet_chain_by_id("999")) == 2


class TestSelectorLists:
    def test_chains_start_with_primary_selector(self):
        assert selectors.CHAINS["tweet"][0] == selectors.TWEET
        assert selectors.CHAINS["menu_block"][0] == selectors.MENU_BLOCK

    def test_every_chain_has_a_fallback(self):
        for name, chain in selectors.CHAINS.items():
            assert len(chain) >= 2, f"{name} için yedek seçici yok"

    def test_required_checks_exist(self):
        required = [check for check in selectors.ALL_CHECKS if check.required]
        names = {check.name for check in required}
        assert "Tweet kutusu" in names
        assert "Engelle satırı" in names

    def test_all_checks_have_turkish_names(self):
        for check in selectors.ALL_CHECKS:
            assert check.name and check.selector


class TestFindHelpers:
    def test_find_first_returns_first_match(self):
        page = FakePage(nodes={"b": [FakeNode(text="ikinci")]})
        found = find_first(page, ("a", "b", "c"))
        assert found is not None
        assert found[0] == "b"
        assert found[1].inner_text() == "ikinci"

    def test_find_first_returns_none(self):
        assert find_first(FakePage(nodes={}), ("a", "b")) is None

    def test_require_first_raises_with_help(self):
        session = FakeSession()
        with pytest.raises(SelectorNotFound) as info:
            require_first(FakePage(nodes={}), ("a",), what="tweet kutusu", session=session)
        message = str(info.value)
        assert "Arayüz öğesi bulunamadı: tweet kutusu" in message
        assert "selectors.py" in message
        assert "check-selectors" in message
        assert session.saved == ["secici-yok-tweet kutusu"]
        assert info.value.selector == "a"

    def test_require_first_without_session(self):
        with pytest.raises(SelectorNotFound) as info:
            require_first(FakePage(nodes={}), ("a",), what="x")
        assert info.value.evidence == ()

    def test_wait_for_first_returns_visible_selector(self):
        page = FakePage(nodes={"b": [FakeNode()]}, visible={"b"})
        assert wait_for_first(page, ("a", "b"), what="öğe", timeout_ms=2000) == "b"

    def test_wait_for_first_raises_when_nothing_appears(self):
        page = FakePage(nodes={}, visible=set())
        with pytest.raises(SelectorNotFound):
            wait_for_first(page, ("a", "b"), what="öğe", timeout_ms=2000)


class TestNotify:
    def test_disabled_notification_returns_false(self):
        assert notify("başlık", "mesaj", enabled=False) is False

    def test_error_file_is_written(self, tmp_path):
        path = write_error_file(tmp_path, "XBot durdu", "CAPTCHA göründü")
        assert path is not None
        assert path.name == ERROR_FILE_NAME
        content = path.read_text(encoding="utf-8")
        assert "XBot durdu" in content
        assert "CAPTCHA göründü" in content

    def test_error_file_creates_directory(self, tmp_path):
        path = write_error_file(tmp_path / "yeni" / "klasor", "a", "b")
        assert path is not None and path.exists()
