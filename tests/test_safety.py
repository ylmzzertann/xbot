"""Guvenlik freni testleri: beklenmeyen sayfa gorulunce durmali."""

from __future__ import annotations

import pytest

from xbot.errors import SafetyStop
from xbot.safety import CAPTCHA, ERROR, LOGIN, OK, RESTRICTED, assert_safe, classify_page

from fakes import FakePage, FakeSession


class TestClassifyPage:
    def test_normal_search_page_is_ok(self):
        state = classify_page(
            "https://x.com/search?q=galatasaray&f=live", "tweetler burada"
        )
        assert state.kind == OK
        assert state.is_ok is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://x.com/i/flow/login",
            "https://x.com/login",
            "https://x.com/account/access",
            "https://twitter.com/i/flow/password_reset",
        ],
    )
    def test_login_urls(self, url):
        assert classify_page(url, "").kind == LOGIN

    @pytest.mark.parametrize(
        "url",
        ["https://client-api.arkoselabs.com/x", "https://x.com/challenge/abc"],
    )
    def test_captcha_urls(self, url):
        assert classify_page(url, "").kind == CAPTCHA

    def test_captcha_text(self):
        state = classify_page("https://x.com/home", "Lütfen insan olduğunu doğrula")
        assert state.kind == CAPTCHA
        assert "insan olduğunu doğrula" in state.marker

    def test_suspicious_login_text(self):
        assert classify_page("https://x.com/home", "Şüpheli giriş denemesi").kind == CAPTCHA

    def test_restricted_text(self):
        state = classify_page("https://x.com/home", "Hesabınız kısıtlandı")
        assert state.kind == RESTRICTED

    def test_suspended_text_english(self):
        assert classify_page("https://x.com/home", "Account is suspended").kind == RESTRICTED

    def test_login_text(self):
        assert classify_page("https://x.com/home", "Sign in to X").kind == LOGIN

    def test_error_text(self):
        assert classify_page("https://x.com/home", "Something went wrong").kind == ERROR

    def test_title_is_checked(self):
        state = classify_page("https://x.com/home", "boş", title="Hesabın askıya alındı")
        assert state.kind == RESTRICTED

    def test_ordinary_tweet_words_do_not_trigger(self):
        """Tweet metninde gecen siradan kelimeler yanlis alarm vermemeli."""
        text = "giriş yaptım stada, hakem hata yaptı, bir şeyler eksik ama kazandık"
        assert classify_page("https://x.com/search?q=x&f=live", text).kind == OK

    def test_message_is_turkish_and_actionable(self):
        state = classify_page("https://x.com/i/flow/login", "")
        assert "login" in state.message
        assert "Oturum" in state.message or "oturum" in state.message


class TestAssertSafe:
    def test_ok_page_passes(self):
        page = FakePage(body="normal tweetler")
        assert assert_safe(page) is None

    def test_captcha_raises_and_saves_evidence(self):
        page = FakePage(body="Verify you are human")
        session = FakeSession()
        with pytest.raises(SafetyStop) as info:
            assert_safe(page, session=session, context="tarama")
        assert info.value.kind == CAPTCHA
        assert session.saved == ["durdu-captcha"]
        assert info.value.evidence == ("durdu-captcha.png", "durdu-captcha.html")
        assert "tarama" in str(info.value)

    def test_login_page_raises(self):
        page = FakePage(url="https://x.com/i/flow/login", body="")
        with pytest.raises(SafetyStop) as info:
            assert_safe(page)
        assert info.value.kind == LOGIN

    def test_evidence_optional_without_session(self):
        page = FakePage(body="Hesabınız kısıtlandı")
        with pytest.raises(SafetyStop) as info:
            assert_safe(page)
        assert info.value.evidence == ()
