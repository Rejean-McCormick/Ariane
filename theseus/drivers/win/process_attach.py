"""
Windows Process Attachment for Theseus.

This module provides utilities to locate running processes and their main
windows on Microsoft Windows. It serves as the initial discovery step for
the Windows driver.

It handles:
- Finding a process by executable name (e.g. "notepad.exe").
- Finding a window by title (e.g. "Untitled - Notepad").
- Attaching `pywinauto` to the target application.

Dependencies:
    - pywinauto
    - psutil (for process enumeration)
"""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

# Optional imports to allow loading on non-Windows systems for linting
try:
    import psutil
    from pywinauto import Application, Desktop
    from pywinauto.timings import TimeoutError as PyWinTimeoutError
except ImportError:
    psutil = None
    Application = None
    Desktop = None
    PyWinTimeoutError = TimeoutError

LOG = logging.getLogger(__name__)


class ProcessDiscoveryError(Exception):
    """Raised when a process or window cannot be found."""


def _check_deps() -> None:
    if Application is None or psutil is None:
        raise ImportError(
            "Missing dependencies for Windows driver. "
            "Please install: pip install pywinauto psutil"
        )


def find_process_id(name: str) -> Optional[int]:
    """
    Find the Process ID (PID) of a running application by name.

    Args:
        name: Executable name (e.g. "notepad.exe" or just "notepad").

    Returns:
        The PID of the first matching process, or None if not found.
    """
    _check_deps()
    target = name.lower()
    if not target.endswith(".exe"):
        target += ".exe"

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() == target:
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return None


def attach_by_pid(pid: int, backend: str = "uia") -> Any:
    """
    Attach pywinauto to a process by PID.

    Args:
        pid: Process ID.
        backend: 'uia' (recommended for modern apps) or 'win32' (legacy).

    Returns:
        A pywinauto.application.Application instance connected to the process.
    """
    _check_deps()
    try:
        app = Application(backend=backend).connect(process=pid)
        LOG.info("Attached to PID %d using backend '%s'", pid, backend)
        return app
    except Exception as e:
        raise ProcessDiscoveryError(f"Failed to attach to PID {pid}: {e}") from e


def attach_by_title(
    title_regex: str, 
    timeout: float = 5.0, 
    backend: str = "uia"
) -> Any:
    """
    Find and attach to an application by its window title.

    Args:
        title_regex: Regex string for the window title.
        timeout: Max seconds to wait for the window.
        backend: 'uia' or 'win32'.

    Returns:
        A pywinauto.application.Application instance.
    """
    _check_deps()
    LOG.info("Waiting for window matching title '%s'...", title_regex)
    try:
        app = Application(backend=backend).connect(
            title_re=title_regex, 
            timeout=timeout
        )
        return app
    except Exception as e:
        raise ProcessDiscoveryError(
            f"Failed to attach to window matching '{title_regex}': {e}"
        ) from e


def launch_application(
    cmd_line: str, 
    backend: str = "uia", 
    wait_for_idle: bool = True
) -> Any:
    """
    Start a new application process.

    Args:
        cmd_line: Command to run (e.g. "notepad.exe").
        backend: 'uia' or 'win32'.
        wait_for_idle: Whether to wait for the app to be idle before returning.

    Returns:
        A pywinauto.application.Application instance.
    """
    _check_deps()
    LOG.info("Launching application: %s", cmd_line)
    try:
        app = Application(backend=backend).start(
            cmd_line, 
            wait_for_idle=wait_for_idle
        )
        return app
    except Exception as e:
        raise ProcessDiscoveryError(f"Failed to launch '{cmd_line}': {e}") from e


def find_main_window(
    app: Any, 
    title_pattern: Optional[str] = None
) -> Any:
    """
    Get the main window object from a connected Application instance.

    Args:
        app: Connected pywinauto Application.
        title_pattern: Optional regex to disambiguate the main window.

    Returns:
        A pywinauto WindowSpecification (wrapper) for the main window.
    """
    try:
        if title_pattern:
            win = app.window(title_re=title_pattern)
        else:
            # Heuristic: pick the top-level window
            win = app.top_window()
        
        # Verify existence
        if not win.exists(timeout=2.0):
            raise ProcessDiscoveryError("Main window not found (exists() returned False)")
            
        return win
    except Exception as e:
        raise ProcessDiscoveryError(f"Failed to locate main window: {e}") from e


def list_open_windows(backend: str = "uia") -> List[str]:
    """
    List titles of all visible top-level windows.
    Useful for debugging configuration.
    """
    _check_deps()
    desktop = Desktop(backend=backend)
    titles = []
    for w in desktop.windows():
        if w.is_visible():
            t = w.window_text()
            if t:
                titles.append(t)
    return titles