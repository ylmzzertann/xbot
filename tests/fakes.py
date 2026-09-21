"""Testler icin sahte DOM/tarayici nesneleri.

Playwright kurulu olmasa bile scraper ve actions katmanlari test edilebilsin
diye, kodun kullandigi kucuk arayuz taklit edilir:

    page.locator(secici) -> .count() / .first / .nth(i)
    node.get_attribute(ad), node.inner_text(), node.click()
    page.wait_for_selector(secici, state=..., timeout=...)
    page.mouse.wheel(...), page.keyboard.press(...)
"""

from __future__ import annotations

from dataclasses import dataclass, field


class FakeNode:
    """Tek bir DOM ogesi."""

    def __init__(
        self,
        children: dict[str, list["FakeNode"]] | None = None,
        *,
        attrs: dict[str, str] | None = None,
        text: str = "",
        on_click=None,
    ) -> None:
        self.children = children or {}
        self.attrs = attrs or {}
        self.text = text
        self.clicks = 0
        self.scrolled = 0
        self.on_click = on_click

    # --- Playwright benzeri arayuz ---

    def locator(self, selector: str) -> "FakeLocator":
        return FakeLocator(self.children.get(selector, []))

    def count(self) -> int:
        return 1

    def get_attribute(self, name: str, **_kwargs) -> str | None:
        return self.attrs.get(name)

    def inner_text(self, **_kwargs) -> str:
        return self.text

    def click(self, **_kwargs) -> None:
        self.clicks += 1
        if self.on_click is not None:
            self.on_click()

    def scroll_into_view_if_needed(self, **_kwargs) -> None:
        self.scrolled += 1


class FakeLocator:
    """Bir secicinin eslesen ogeleri."""

    def __init__(self, nodes: list[FakeNode]) -> None:
        self.nodes = nodes

    def count(self) -> int:
        return len(self.nodes)

    @property
    def first(self) -> FakeNode:
        return self.nodes[0] if self.nodes else FakeNode()

    def nth(self, index: int) -> FakeNode:
        return self.nodes[index]


class FakeMouse:
    def __init__(self) -> None:
        self.wheels = 0

    def wheel(self, _dx: int, _dy: int) -> None:
        self.wheels += 1


class FakeKeyboard:
    def __init__(self) -> None:
        self.presses: list[str] = []

    def press(self, key: str) -> None:
        self.presses.append(key)


class FakePage:
    """Sahte sayfa."""

    def __init__(
        self,
        *,
        url: str = "https://x.com/search?q=test&f=live",
        title: str = "Arama / X",
        body: str = "tweetler",
        nodes: dict[str, list[FakeNode]] | None = None,
        visible: set[str] | None = None,
        hidden: set[str] | None = None,
    ) -> None:
        self.url = url
        self._title = title
        self.body = body
        self.nodes = nodes or {}
        self.visible = visible if visible is not None else set(self.nodes)
        self.hidden: set[str] = hidden or set()
        self.mouse = FakeMouse()
        self.keyboard = FakeKeyboard()
        self.waits: list[tuple[str, str]] = []

    def title(self) -> str:
        return self._title

    def content(self) -> str:
        return f"<html><body>{self.body}</body></html>"

    def inner_text(self, _selector: str) -> str:
        return self.body

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self.nodes.get(selector, []))

    def wait_for_selector(self, selector: str, *, timeout=None, state="visible"):
        self.waits.append((selector, state))
        if state == "hidden":
            if selector in self.hidden or selector not in self.nodes:
                return None
            raise TimeoutError(f"{selector} hâlâ görünür")
        if selector in self.visible and self.nodes.get(selector):
            return self.nodes[selector][0]
        raise TimeoutError(f"{selector} bulunamadı")

    def screenshot(self, **_kwargs) -> None:
        return None

    def goto(self, url: str, **_kwargs) -> None:
        self.url = url


@dataclass
class FakeSession:
    """BrowserSession yerine gecen sahte oturum (kanit kaydini sayar)."""

    saved: list[str] = field(default_factory=list)

    def save_evidence(self, label: str = "kanit") -> tuple[str, ...]:
        self.saved.append(label)
        return (f"{label}.png", f"{label}.html")


# --------------------------------------------------------------------------
# tweet kutusu uretici
# --------------------------------------------------------------------------


def make_tweet_node(
    *,
    username: str = "kotu_hesap",
    tweet_id: str = "1000",
    text: str = "siktir git",
    timestamp: str = "2026-09-20T12:00:00.000Z",
    display_name: str = "Kötü Hesap",
) -> FakeNode:
    """Gercek DOM yapisina benzeyen bir tweet kutusu uretir."""
    from xbot import selectors

    time_node = FakeNode(attrs={"datetime": timestamp})
    permalink = FakeNode(
        {selectors.TIME: [time_node]},
        attrs={"href": f"/{username}/status/{tweet_id}"},
    )
    text_node = FakeNode(text=text)
    name_node = FakeNode(text=f"{display_name}\n@{username}")
    menu_button = FakeNode()
    return FakeNode(
        {
            selectors.PERMALINK: [permalink],
            selectors.TWEET_TEXT: [text_node],
            selectors.USER_NAME: [name_node],
            selectors.TWEET_MENU_BUTTON: [menu_button],
        }
    )


def make_search_page(tweet_nodes: list[FakeNode], **kwargs) -> FakePage:
    """Tweetleri iceren sahte arama sayfasi."""
    from xbot import selectors

    nodes = {selectors.TWEET: tweet_nodes}
    return FakePage(nodes=nodes, **kwargs)
