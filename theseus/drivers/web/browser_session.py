"""
Browser session helper for Theseus (web driver).

This module is a thin, dependency-free wrapper around a "web driver"
object (e.g. Selenium / Playwright / custom), plus the DOMAdapter.

It is responsible for:

- Navigating to URLs (via the injected driver).
- Capturing the current DOM as a DOMSnapshotNode tree.
- Optionally capturing a screenshot.
- Producing a UIState via DOMAdapter.

This module does NOT import Selenium or Playwright directly. Instead, it
expects any injected driver to follow a simple duck-typed protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Protocol

from common.models.ui_state import UIState
from .dom_adapter import DOMAdapter, DOMAdapterConfig, DOMSnapshotNode
from ...core.fingerprint_engine import FingerprintEngine, FingerprintEngineConfig


# --------------------------------------------------------------------------- #
# Driver protocol
# --------------------------------------------------------------------------- #


class WebDriverLike(Protocol):
    """
    Minimal protocol expected from a browser automation driver.

    Typical Selenium-like objects will satisfy this, but you can also
    implement your own wrapper class as long as it exposes these members.
    """

    @property
    def page_source(self) -> str:
        """Return the current page HTML as a string."""
        ...

    @property
    def current_url(self) -> str:
        """Return the current page URL."""
        ...

    def get(self, url: str) -> None:
        """Navigate to the given URL."""
        ...

    # Screenshot methods vary a bit across libraries, so we support two
    # common shapes. At least one of these should exist:

    def get_screenshot_as_png(self) -> bytes:
        """Return a PNG screenshot as bytes (Selenium-style)."""
        ...


# --------------------------------------------------------------------------- #
# HTML → DOMSnapshotNode
# --------------------------------------------------------------------------- #


class _HTMLToDOMParser(HTMLParser):
    """
    Simple HTML → DOMSnapshotNode converter using the stdlib HTMLParser.

    This is intentionally minimal and conservative; it is NOT a full
    browser DOM implementation, but good enough for structural and
    semantic mapping in many cases.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # Synthetic root to handle multiple top-level elements
        self._root = DOMSnapshotNode(tag="document")
        self._stack: List[DOMSnapshotNode] = [self._root]

    @property
    def root(self) -> DOMSnapshotNode:
        return self._root

    # HTMLParser callbacks ------------------------------------------------

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attrs_dict: Dict[str, str] = {}
        for k, v in attrs:
            if v is not None:
                attrs_dict[k] = v

        node = DOMSnapshotNode(tag=tag.lower(), attributes=attrs_dict)
        self._stack[-1].children.append(node)
        self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        if len(self._stack) > 1:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        # Append text to the current node; real browsers split text nodes,
        # but for our purposes concatenation is fine.
        current = self._stack[-1]
        if current.text:
            current.text += " " + text
        else:
            current.text = text


def parse_html_to_dom(html: str) -> DOMSnapshotNode:
    """
    Parse raw HTML into a DOMSnapshotNode tree.

    The root node has tag "document" and its children correspond to
    top-level elements (<html>, etc.).
    """
    parser = _HTMLToDOMParser()
    parser.feed(html)
    parser.close()
    return parser.root


# --------------------------------------------------------------------------- #
# Session config
# --------------------------------------------------------------------------- #


RefFactory = Callable[[bytes], str]


@dataclass
class WebSessionConfig:
    """
    Configuration for WebBrowserSession.

    Attributes:
        app_id:
            Logical identifier for the web application (e.g. "my-web-app").
        locale:
            Optional locale tag to assign to UIStates (e.g. "en-US").
        version:
            Optional application version string.
        screenshot_ref_factory:
            Optional callable that persists screenshot bytes and returns
            a reference string (e.g. file path or URL). If provided, the
            session will capture screenshots in `build_ui_state` and pass
            the resulting reference into the DOMAdapter.
    """

    app_id: str
    locale: Optional[str] = None
    version: Optional[str] = None
    screenshot_ref_factory: Optional[RefFactory] = None


# --------------------------------------------------------------------------- #
# Browser session
# --------------------------------------------------------------------------- #


@dataclass
class WebBrowserSession:
    """
    High-level helper around a WebDriverLike + DOMAdapter.

    Typical usage:

        driver = selenium.webdriver.Firefox(...)
        session = WebBrowserSession.with_defaults(driver, app_id="my-app")

        session.navigate("https://example.com")
        ui_state = session.build_ui_state()

    You can also control fingerprinting and DOMAdapter behavior by
    constructing the FingerprintEngine and DOMAdapter yourself and
    passing them into the constructor.
    """

    driver: WebDriverLike
    config: WebSessionConfig
    dom_adapter: DOMAdapter

    @classmethod
    def with_defaults(
        cls,
        driver: WebDriverLike,
        app_id: str,
        *,
        locale: Optional[str] = None,
        version: Optional[str] = None,
        screenshot_ref_factory: Optional[RefFactory] = None,
        dom_adapter_config: Optional[DOMAdapterConfig] = None,
        fingerprint_config: Optional[FingerprintEngineConfig] = None,
    ) -> "WebBrowserSession":
        """
        Convenience constructor that wires up a default FingerprintEngine
        and DOMAdapter.
        """
        fp_engine = FingerprintEngine(config=fingerprint_config)
        adapter = DOMAdapter(
            fingerprint_engine=fp_engine,
            config=dom_adapter_config,
        )
        cfg = WebSessionConfig(
            app_id=app_id,
            locale=locale,
            version=version,
            screenshot_ref_factory=screenshot_ref_factory,
        )
        return cls(driver=driver, config=cfg, dom_adapter=adapter)

    # ------------------------------------------------------------------ #
    # Navigation & capture
    # ------------------------------------------------------------------ #

    def navigate(self, url: str) -> None:
        """
        Navigate the underlying driver to the given URL.
        """
        self.driver.get(url)

    @property
    def current_url(self) -> Optional[str]:
        """
        Return the current URL, if the driver exposes it.
        """
        try:
            return self.driver.current_url
        except Exception:
            return None

    def capture_dom_snapshot(self) -> DOMSnapshotNode:
        """
        Capture the current DOM as a DOMSnapshotNode tree.

        Uses `driver.page_source` and the stdlib HTMLParser. If the driver
        does not expose `page_source`, a RuntimeError is raised.
        """
        html = getattr(self.driver, "page_source", None)
        if not html:
            raise RuntimeError("WebDriverLike object does not expose 'page_source'")
        return parse_html_to_dom(html)

    def capture_screenshot_bytes(self) -> bytes:
        """
        Capture a screenshot from the driver and return raw bytes.

        This method expects the driver to implement `get_screenshot_as_png`.
        If not available, a RuntimeError is raised.
        """
        if hasattr(self.driver, "get_screenshot_as_png"):
            return self.driver.get_screenshot_as_png()
        raise RuntimeError(
            "WebDriverLike object does not implement 'get_screenshot_as_png'"
        )

    # ------------------------------------------------------------------ #
    # UIState construction
    # ------------------------------------------------------------------ #

    def build_ui_state(self) -> UIState:
        """
        Build a UIState for the current browser view.

        Steps:
            1. Capture the DOM as a DOMSnapshotNode tree.
            2. Optionally capture a screenshot and obtain a reference via
               `screenshot_ref_factory`.
            3. Use DOMAdapter to build a UIState with fingerprints and
               interactive elements.

        Returns:
            UIState instance.
        """
        root = self.capture_dom_snapshot()

        screenshot_ref: Optional[str] = None
        if self.config.screenshot_ref_factory is not None:
            screenshot_bytes = self.capture_screenshot_bytes()
            screenshot_ref = self.config.screenshot_ref_factory(screenshot_bytes)

        state = self.dom_adapter.build_ui_state(
            root=root,
            app_id=self.config.app_id,
            url=self.current_url,
            screenshot_ref=screenshot_ref,
            locale=self.config.locale,
            version=self.config.version,
        )
        return state
