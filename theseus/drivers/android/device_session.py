"""
Android Device Session for Theseus.

This module provides an ExplorationDriver implementation for Android devices.
It acts as the bridge between the high-level exploration engine and a low-level
Android driver (such as uiautomator2, adb, or Appium).

Responsibilities:
- Managing the device connection session.
- Capturing the screen hierarchy (XML) and converting it to UIState.
- Translating abstract Actions into device events (tap, input, key events).
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

from common.models.transition import ActionType
from common.models.ui_state import UIState, InteractiveElement
from theseus.core.exploration_engine import CandidateAction
from theseus.drivers.android.accessibility_adapter import (
    AccessibilityAdapter,
    AndroidAdapterConfig,
    AndroidNode,
)
from ...core.fingerprint_engine import FingerprintEngine, FingerprintEngineConfig

LOG = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Driver Protocol
# --------------------------------------------------------------------------- #


class DeviceDriverLike(Protocol):
    """
    Protocol expected from the underlying Android driver.
    Compatible with typical uiautomator2 or custom adb wrappers.
    """

    def dump_hierarchy(self) -> str:
        """Return the current window hierarchy as an XML string."""
        ...

    def click(self, x: int, y: int) -> None:
        """Tap at the specific coordinates."""
        ...

    def send_keys(self, text: str) -> None:
        """Type text into the currently focused field."""
        ...

    def press(self, key_code: str) -> None:
        """
        Press a physical key.
        Common codes: 'home', 'back', 'enter', 'delete'.
        """
        ...

    def app_start(self, package_name: str) -> None:
        """Launch or bring to front the specified package."""
        ...

    def app_stop(self, package_name: str) -> None:
        """Force stop the specified package."""
        ...

    def screenshot(self) -> bytes:
        """Return raw PNG bytes of the current screen."""
        ...

    @property
    def current_app(self) -> Dict[str, str]:
        """
        Return metadata about current running app.
        Expected keys: 'package', 'activity'.
        """
        ...


# --------------------------------------------------------------------------- #
# Session Configuration
# --------------------------------------------------------------------------- #


@dataclass
class AndroidSessionConfig:
    """
    Configuration for AndroidDeviceSession.
    """

    app_package: str
    app_activity: Optional[str] = None
    
    # Wait time (seconds) after an action before capturing state
    action_delay: float = 2.0
    
    locale: str = "en-US"
    version: Optional[str] = None


# --------------------------------------------------------------------------- #
# Device Session Implementation
# --------------------------------------------------------------------------- #


class AndroidDeviceSession:
    """
    ExplorationDriver implementation for Android.
    """

    def __init__(
        self,
        driver: DeviceDriverLike,
        config: AndroidSessionConfig,
        adapter_config: Optional[AndroidAdapterConfig] = None,
        fingerprint_config: Optional[FingerprintEngineConfig] = None,
    ) -> None:
        self.driver = driver
        self.config = config
        
        # Initialize adapter pipeline
        fp_engine = FingerprintEngine(config=fingerprint_config)
        self.adapter = AccessibilityAdapter(
            fingerprint_engine=fp_engine,
            config=adapter_config,
        )

    # ------------------------------------------------------------------ #
    # ExplorationDriver Protocol
    # ------------------------------------------------------------------ #

    def reset(self) -> UIState:
        """
        Reset the session by restarting the target application.
        """
        LOG.info("Resetting session: restarting package %s", self.config.app_package)
        
        # Stop and start to ensure clean state
        try:
            self.driver.app_stop(self.config.app_package)
            time.sleep(1.0)
            self.driver.app_start(self.config.app_package)
            
            # Wait for app to settle
            time.sleep(self.config.action_delay * 2)
        except Exception as e:
            LOG.error("Failed to reset app: %s", e)
            # Proceed anyway, we might be attached to an existing session

        return self.capture_state()

    def capture_state(self) -> UIState:
        """
        Capture the current screen hierarchy and convert to UIState.
        """
        # 1. Get raw hierarchy XML
        try:
            xml_source = self.driver.dump_hierarchy()
        except Exception as e:
            LOG.error("Failed to dump hierarchy: %s", e)
            # Return empty/error state or re-raise based on policy
            raise RuntimeError("Device communication failed") from e

        # 2. Parse XML into AndroidNode tree
        root_node = self._parse_xml_hierarchy(xml_source)

        # 3. Get current activity info
        app_info = self.driver.current_app
        current_package = app_info.get("package")
        current_activity = app_info.get("activity")

        # 4. Optional Screenshot (if supported/configured)
        # Note: In high-speed crawling, we might skip screenshots or cache refs
        screenshot_ref = None 
        # Future: implement screenshot capture and persistence here

        # 5. Build UIState via Adapter
        return self.adapter.build_ui_state(
            root=root_node,
            app_id=self.config.app_package,
            activity=current_activity,
            screenshot_ref=screenshot_ref,
            locale=self.config.locale,
            version=self.config.version
        )

    def list_actions(self, state: UIState) -> List[CandidateAction]:
        """
        Generate candidate actions from the captured UIState.
        """
        actions: List[CandidateAction] = []

        # 1. Interactive Elements (Click/Tap)
        for element in state.interactive_elements:
            if not element.visible or not element.enabled:
                continue

            # Skip elements without bounds (cannot tap)
            if not element.bounding_box:
                continue

            # Create CLICK action
            actions.append(
                CandidateAction(
                    id=f"click_{element.id}",
                    element_id=element.id,
                    action_type=ActionType.CLICK,
                    label=f"Tap {element.label or element.role}",
                    metadata={
                        "bounds": element.bounding_box.as_tuple()
                    }
                )
            )

            # If it's a text field, create TEXT_INPUT action
            if element.role in ("textbox", "edittext"):
                actions.append(
                    CandidateAction(
                        id=f"input_{element.id}",
                        element_id=element.id,
                        action_type=ActionType.TEXT_INPUT,
                        label=f"Type into {element.label or 'field'}",
                        metadata={
                            "bounds": element.bounding_box.as_tuple()
                        }
                    )
                )

        # 2. Global Keys (Back button)
        # Always add a 'Back' action as a navigation option
        actions.append(
            CandidateAction(
                id="global_back",
                element_id=None,
                action_type=ActionType.KEY,
                label="Press Back",
                metadata={"key_code": "back"}
            )
        )

        return actions

    def perform_action(self, state: UIState, action: CandidateAction) -> None:
        """
        Execute the candidate action on the device.
        """
        LOG.debug("Performing action: %s", action.label)

        try:
            if action.action_type == ActionType.CLICK:
                bbox = action.metadata.get("bounds") # (x, y, w, h)
                if bbox:
                    x, y, w, h = bbox
                    center_x = x + (w // 2)
                    center_y = y + (h // 2)
                    self.driver.click(center_x, center_y)

            elif action.action_type == ActionType.TEXT_INPUT:
                # Click to focus first
                bbox = action.metadata.get("bounds")
                if bbox:
                    x, y, w, h = bbox
                    self.driver.click(x + w//2, y + h//2)
                    time.sleep(0.5) # Wait for focus
                
                # Input placeholder text (Theseus usually just explores, doesn't fill specific data yet)
                # In a real scanner, we might want a strategy for input data.
                self.driver.send_keys("test_input") 
                self.driver.press("enter")

            elif action.action_type == ActionType.KEY:
                key_code = action.metadata.get("key_code")
                if key_code:
                    self.driver.press(key_code)

            # Wait for UI to settle after action
            time.sleep(self.config.action_delay)

        except Exception as e:
            LOG.error("Failed to perform action %s: %s", action.id, e)
            raise

    # ------------------------------------------------------------------ #
    # Parsing Logic (XML -> AndroidNode)
    # ------------------------------------------------------------------ #

    def _parse_xml_hierarchy(self, xml_string: str) -> AndroidNode:
        """
        Parse Android standard XML dump into AndroidNode tree.
        Handles standard 'node' attributes from uiautomator dumps.
        """
        try:
            # Clean XML string if necessary (sometimes uiautomator adds junk)
            root_element = ET.fromstring(xml_string)
        except ET.ParseError:
            # Fallback for empty or malformed XML
            return AndroidNode(class_name="Root", package_name="unknown")

        return self._convert_element(root_element)

    def _convert_element(self, element: ET.Element) -> AndroidNode:
        """Recursive helper to convert ET.Element to AndroidNode."""
        
        # Parse boolean flags safely
        def get_bool(key: str) -> bool:
            return element.attrib.get(key, "false").lower() == "true"

        # Bounds usually come as "[0,0][100,100]"
        bounds = element.attrib.get("bounds", "[0,0][0,0]")

        node = AndroidNode(
            class_name=element.attrib.get("class", "android.view.View"),
            package_name=element.attrib.get("package"),
            resource_id=element.attrib.get("resource-id"),
            content_desc=element.attrib.get("content-desc"),
            text=element.attrib.get("text"),
            bounds=bounds,
            clickable=get_bool("clickable"),
            checked=get_bool("checked"),
            checkable=get_bool("checkable"),
            editable=get_bool("editable"), # Note: not always present in standard XML
            enabled=get_bool("enabled"),
            focusable=get_bool("focusable"),
            focused=get_bool("focused"),
            scrollable=get_bool("scrollable"),
            selected=get_bool("selected"),
            # Visible isn't explicitly in standard dump, inferred if present in tree
            visible_to_user=True 
        )

        # Recurse children
        for child in element:
            node.children.append(self._convert_element(child))

        return node