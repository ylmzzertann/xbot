"""TUM CSS/data-testid seCicileri BU DOSYADA.

X arayuzu degistiginde tek yer duzeltilir. Kod baska hicbir yerde ham secici
yazmaz.

Tasarim notlari
---------------
1. Her onemli oge icin BIRDEN FAZLA secici verilir (ilk bulunan kullanilir).
   Boylece X kucuk bir degisiklik yaptiginda program tamamen durmaz.
2. En saglam bilgi kaynagi tweetin kalici baglantisidir:
   <a href="/kullanici/status/1234567890"> ... hem kullanici adi hem tweet id
   buradan cikar. Kullanici adini ayrica "User-Name" bloguyla dogrulariz.
3. Secici bulunamazsa program SESSIZCE DEVAM ETMEZ: SelectorNotFound yukseltir,
   ekran goruntusu + sayfa HTML'i kaydedilir (spesifikasyon madde 5).
4. Bu seciciler "check-selectors" komutuyla CANLI sayfada dogrulanir:
       python -m xbot login
       python -m xbot check-selectors
   Komut her seciciyi tek tek dener ve kac tane bulundugunu yazar.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

# --------------------------------------------------------------------------
# adresler
# --------------------------------------------------------------------------

BASE_URL = "https://x.com"
HOME_URL = f"{BASE_URL}/home"
EXPLORE_URL = f"{BASE_URL}/explore"


def search_url(query: str, *, latest: bool = True) -> str:
    """Arama adresi. latest=True -> "Son" (Latest) sekmesi."""
    parts = [f"q={quote(query)}", "src=typed_query"]
    if latest:
        parts.append("f=live")
    return f"{BASE_URL}/search?{'&'.join(parts)}"


def profile_url(username: str) -> str:
    return f"{BASE_URL}/{username.lstrip('@')}"


def following_url(username: str) -> str:
    return f"{profile_url(username)}/following"


def followers_url(username: str) -> str:
    return f"{profile_url(username)}/verified_followers"


def status_url(username: str, tweet_id: str) -> str:
    return f"{profile_url(username)}/status/{tweet_id}"


# --------------------------------------------------------------------------
# sayfa iskeleti
# --------------------------------------------------------------------------

PRIMARY_COLUMN = '[data-testid="primaryColumn"]'
TIMELINE = '[aria-label][role="region"], [data-testid="primaryColumn"]'
CELL = '[data-testid="cellInnerDiv"]'
EMPTY_STATE = '[data-testid="empty_state_header_text"]'
RETRY_BUTTON = '[role="button"]:has-text("Yeniden dene")'

# giris durumu
ACCOUNT_SWITCHER = '[data-testid="SideNav_AccountSwitcher_Button"]'
SIDE_NAV_HOME = '[data-testid="AppTabBar_Home_Link"]'
LOGIN_BUTTON = '[data-testid="loginButton"]'
SEARCH_INPUT = '[data-testid="SearchBox_Search_Input"]'

# --------------------------------------------------------------------------
# tweet
# --------------------------------------------------------------------------

#: Zaman tunelindeki tek bir tweet
TWEET = 'article[data-testid="tweet"]'
TWEET_FALLBACKS = ('article[role="article"]', "article")

#: Tweet metni (birden fazla parca olabilir: metin + emoji + link)
TWEET_TEXT = '[data-testid="tweetText"]'
TWEET_TEXT_FALLBACKS = ("div[lang]",)

#: Kullanici adi blogu ("Ad Soyad @kullanici . 5dk")
USER_NAME = '[data-testid="User-Name"]'

#: Tweetin kalici baglantisi + tarihi: <a href="/user/status/123"><time datetime=...>
PERMALINK = 'a[href*="/status/"]:has(time)'
PERMALINK_FALLBACKS = ('a[href*="/status/"]',)
TIME = "time"

#: Retweet/yanit baglami (kimin retweetledigi)
SOCIAL_CONTEXT = '[data-testid="socialContext"]'

def tweet_by_id(tweet_id: str) -> str:
    """Belirli bir tweetin kutusunu bulan secici (engelleme icin).

    Baglanti "/status/<id>" ile BITMELI ($=): boylece "/status/111" aranirken
    "/status/1112345" yanlislikla eslesmez.
    """
    return f'article[data-testid="tweet"]:has(a[href$="/status/{tweet_id}"])'


def tweet_by_id_fallback(tweet_id: str) -> str:
    return f'article:has(a[href*="/status/{tweet_id}"])'


def tweet_chain_by_id(tweet_id: str) -> tuple[str, ...]:
    return (tweet_by_id(tweet_id), tweet_by_id_fallback(tweet_id))


# --------------------------------------------------------------------------
# engelleme akisi
# --------------------------------------------------------------------------

#: Tweetin sagindaki "..." dugmesi
TWEET_MENU_BUTTON = '[data-testid="caret"]'
TWEET_MENU_BUTTON_FALLBACKS = ('[aria-label="Daha fazla"]', '[aria-label="More"]')

#: Acilan menu
DROPDOWN = '[data-testid="Dropdown"]'
DROPDOWN_FALLBACKS = ('[role="menu"]',)

#: Menudeki "Engelle" satiri
MENU_BLOCK = '[data-testid="block"]'
MENU_BLOCK_FALLBACKS = (
    '[role="menuitem"]:has-text("Engelle")',
    '[role="menuitem"]:has-text("Block")',
)
MENU_MUTE = '[data-testid="mute"]'  # ileride "sessize alma" secenegi icin

#: Onay penceresi
CONFIRM_SHEET = '[data-testid="confirmationSheetDialog"]'
CONFIRM_BUTTON = '[data-testid="confirmationSheetConfirm"]'
CONFIRM_BUTTON_FALLBACKS = (
    '[role="button"]:has-text("Engelle")',
    '[role="button"]:has-text("Block")',
)
CANCEL_BUTTON = '[data-testid="confirmationSheetCancel"]'

#: Engelledikten sonra gorunen durum (dogrulama icin)
UNBLOCK_BUTTON = '[data-testid="unblock"]'
BLOCKED_TOAST = '[data-testid="toast"]'

# --------------------------------------------------------------------------
# takip listesi (sync-whitelist)
# --------------------------------------------------------------------------

USER_CELL = '[data-testid="UserCell"]'
USER_CELL_LINK = '[data-testid="UserCell"] a[role="link"][href^="/"]'


# --------------------------------------------------------------------------
# canli dogrulama listesi
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SelectorCheck:
    """check-selectors komutunun tek satiri."""

    name: str
    selector: str
    required: bool
    where: str  # hangi sayfada beklenir
    note: str = ""


#: Arama sayfasinda ("Son" sekmesi) beklenen ogeler
SEARCH_PAGE_CHECKS: tuple[SelectorCheck, ...] = (
    SelectorCheck("Ana kolon", PRIMARY_COLUMN, True, "arama"),
    SelectorCheck("Tweet kutusu", TWEET, True, "arama"),
    SelectorCheck("Tweet metni", TWEET_TEXT, True, "arama"),
    SelectorCheck("Kullanıcı adı bloğu", USER_NAME, True, "arama"),
    SelectorCheck("Kalıcı bağlantı + zaman", PERMALINK, True, "arama"),
    SelectorCheck('"..." menü düğmesi', TWEET_MENU_BUTTON, True, "arama"),
    SelectorCheck("Oturum göstergesi", ACCOUNT_SWITCHER, False, "arama", "giriş yapılmışsa görünür"),
    SelectorCheck("Sonuç yok uyarısı", EMPTY_STATE, False, "arama", "sonuç yoksa görünür"),
)

#: Menu acildiktan sonra beklenen ogeler (engelleme akisi)
MENU_CHECKS: tuple[SelectorCheck, ...] = (
    SelectorCheck("Açılan menü", DROPDOWN, True, "menü"),
    SelectorCheck("Engelle satırı", MENU_BLOCK, True, "menü"),
)

ALL_CHECKS = SEARCH_PAGE_CHECKS + MENU_CHECKS


def with_fallbacks(primary: str, fallbacks: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Bir secici ve yedeklerini tek demet halinde verir."""
    return (primary, *fallbacks)


#: Kodun kullandigi secici zincirleri (ilk bulunan kazanir)
CHAINS = {
    "tweet": with_fallbacks(TWEET, TWEET_FALLBACKS),
    "tweet_text": with_fallbacks(TWEET_TEXT, TWEET_TEXT_FALLBACKS),
    "permalink": with_fallbacks(PERMALINK, PERMALINK_FALLBACKS),
    "menu_button": with_fallbacks(TWEET_MENU_BUTTON, TWEET_MENU_BUTTON_FALLBACKS),
    "dropdown": with_fallbacks(DROPDOWN, DROPDOWN_FALLBACKS),
    "menu_block": with_fallbacks(MENU_BLOCK, MENU_BLOCK_FALLBACKS),
    "confirm": with_fallbacks(CONFIRM_BUTTON, CONFIRM_BUTTON_FALLBACKS),
}
