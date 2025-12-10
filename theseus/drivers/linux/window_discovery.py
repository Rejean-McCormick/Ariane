"""
Linux Window Discovery for Theseus.

This module provides utilities to locate running applications and windows
on the Linux desktop using the AT-SPI registry.

It abstracts the details of querying the accessibility bus to find a
target application by name or role, returning the raw AT-SPI accessible
objects that the driver can then use.

Dependencies:
    - pyatspi (standard Linux accessibility bridge)
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, List, Optional

# Try to import pyatspi, but don't crash at import time if missing
# (This allows the module to be loaded in non-Linux environments for linting)
try:
    import pyatspi  # type: ignore[import]
except ImportError:
    pyatspi = None

LOG = logging.getLogger(__name__)


class WindowDiscoveryError(Exception):
    """Raised when an application or window cannot be found."""


def _check_atspi() -> None:
    if pyatspi is None:
        raise ImportError(
            "pyatspi is not installed. "
            "Please install python3-pyatspi or equivalent for your distro."
        )


def get_desktop(i: int = 0) -> Any:
    """
    Get the root Desktop object from the AT-SPI registry.
    """
    _check_atspi()
    try:
        return pyatspi.Registry.getDesktop(i)
    except Exception as e:
        raise WindowDiscoveryError(f"Failed to connect to AT-SPI registry: {e}") from e


def list_applications() -> List[Any]:
    """
    List all accessible applications currently running on the desktop.
    """
    desktop = get_desktop()
    apps = []
    count = desktop.childCount
    for i in range(count):
        try:
            child = desktop.getChildAtIndex(i)
            if child and child.getRoleName() == "application":
                apps.append(child)
        except Exception:
            # Ignore transient errors accessing children
            continue
    return apps


def find_application(
    app_name: str, 
    timeout: float = 5.0,
    retry_interval: float = 0.5
) -> Any:
    """
    Find an application by its name (case-insensitive substring match).

    Args:
        app_name: Name to search for (e.g. "gedit", "firefox").
        timeout: Max seconds to wait for the app to appear.
        retry_interval: Seconds between retries.

    Returns:
        The raw AT-SPI application object.

    Raises:
        WindowDiscoveryError if not found after timeout.
    """
    _check_atspi()
    LOG.info("Waiting for application matching '%s'...", app_name)
    
    end_time = time.time() + timeout
    pattern = re.compile(re.escape(app_name), re.IGNORECASE)

    while time.time() < end_time:
        desktop = get_desktop()
        for i in range(desktop.childCount):
            try:
                child = desktop.getChildAtIndex(i)
                if not child:
                    continue
                
                # Check name
                if pattern.search(child.name):
                    LOG.info("Found application: '%s'", child.name)
                    return child
            except Exception:
                continue
        
        time.sleep(retry_interval)

    raise WindowDiscoveryError(f"Application '{app_name}' not found after {timeout}s")


def find_window_in_app(
    app: Any, 
    title_pattern: Optional[str] = None
) -> Any:
    """
    Find the main window within an application.

    Args:
        app: The AT-SPI application object.
        title_pattern: Optional regex string to match window title. 
                       If None, returns the first found frame/window.

    Returns:
        The raw AT-SPI window object.
    """
    LOG.debug("Searching for window in app '%s'", app.name)
    
    # Common roles for top-level windows
    window_roles = {"frame", "dialog", "window"}
    
    regex = None
    if title_pattern:
        regex = re.compile(title_pattern, re.IGNORECASE)

    # 1. Direct children search
    for i in range(app.childCount):
        try:
            child = app.getChildAtIndex(i)
            if not child:
                continue
                
            role = child.getRoleName()
            if role in window_roles:
                # If pattern provided, check match
                if regex:
                    if regex.search(child.name):
                        return child
                else:
                    # No pattern, return first window
                    return child
        except Exception:
            continue

    raise WindowDiscoveryError(
        f"No window found in app '{app.name}' matching '{title_pattern or '*'}'"
    )


def dump_debug_info() -> None:
    """
    Print a tree of currently running applications for debugging.
    """
    try:
        desktop = get_desktop()
        print(f"Desktop: {desktop.name} (children: {desktop.childCount})")
        for i in range(desktop.childCount):
            app = desktop.getChildAtIndex(i)
            print(f"  - [{app.getRoleName()}] {app.name}")
    except Exception as e:
        print(f"Failed to dump debug info: {e}")