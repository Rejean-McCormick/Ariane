"""
Recording primitives for human-guided workflows in Theseus.

This package provides tools to record UI interaction sequences performed
by a human operator, while still producing the same data structures used
by automated exploration:

- UIState instances (from `common.models.ui_state`)
- Transition instances (from `common.models.transition`)

The primary entry points are:

- SessionRecorder: wraps an ExplorationDriver and a StateTracker to
  capture (state_before, action, state_after) triples for each human step.
- Optional helper utilities in `prompts.py` to annotate intents and
  descriptions interactively.

These recording tools are intended to:

- Fill gaps where full automation is impossible or unsafe.
- Generate high-quality, human-verified paths for ingestion into Atlas.
"""

from .session_recorder import SessionRecorder, RecordingStep

__all__ = [
    "SessionRecorder",
    "RecordingStep",
]
