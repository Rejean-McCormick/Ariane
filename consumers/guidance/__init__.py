"""
Guidance Client package.

This package contains the core, framework-agnostic building blocks for
Ariane's Guidance Client:

- Data models for guidance goals, plans, steps, and sessions.
- Probe interfaces for capturing local UI snapshots.
- Matching logic to resolve snapshots to known Atlas states.
- The guidance engine that ties Atlas, probes, and models together.

This package does NOT perform any UI rendering or direct user I/O.
Presentation layers (CLI tools, GUIs, overlays, etc.) should import
and consume these primitives.
"""

from .models import (
    GoalType,
    GuidanceGoal,
    StateMatchDetails,
    StateMatchResult,
    GuidanceStepKind,
    GuidanceStep,
    GuidancePlanStatus,
    GuidancePlan,
    SessionStatus,
    GuidanceSessionState,
)
from .probe_interface import (
    ProbingError,
    BoundingBoxSnapshot,
    LocalElementSnapshot,
    LocalUISnapshot,
    GuidanceProbe,
    NullProbe,
)
from .matching import (
    MatchingConfig,
    score_state_match,
    match_states,
    best_match,
)
from .engine import (
    GuidanceEngineError,
    GuidanceEngineConfig,
    GuidanceEngine,
)

__all__ = [
    # models
    "GoalType",
    "GuidanceGoal",
    "StateMatchDetails",
    "StateMatchResult",
    "GuidanceStepKind",
    "GuidanceStep",
    "GuidancePlanStatus",
    "GuidancePlan",
    "SessionStatus",
    "GuidanceSessionState",
    # probe_interface
    "ProbingError",
    "BoundingBoxSnapshot",
    "LocalElementSnapshot",
    "LocalUISnapshot",
    "GuidanceProbe",
    "NullProbe",
    # matching
    "MatchingConfig",
    "score_state_match",
    "match_states",
    "best_match",
    # engine
    "GuidanceEngineError",
    "GuidanceEngineConfig",
    "GuidanceEngine",
]
