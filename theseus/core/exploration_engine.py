"""
Exploration engine for Theseus.

This module coordinates exploration of a target application using a
driver, and records discovered states and transitions.

Responsibilities:

- Start from an initial UI state captured by a driver.
- Traverse the UI by applying actions (DFS-style exploration).
- Use StateTracker to deduplicate states.
- Produce Transition objects describing observed edges.

This layer is **driver-agnostic**. It relies on a small driver
interface (ExplorationDriver) that concrete drivers must implement.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple

from common.models.ui_state import UIState
from common.models.transition import Action, ActionType, Transition
from .state_tracker import StateTracker, StateTrackerConfig

LOG = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Driver protocol and action candidates
# --------------------------------------------------------------------------- #


@dataclass
class CandidateAction:
    """
    Driver-level description of a possible interaction.

    The exploration engine treats this as an opaque handle that the driver
    understands. It uses element_id / type / label only for building the
    recorded Transition, not for performing the action itself.

    Attributes:
        id:
            Driver-defined opaque identifier for this action. Not persisted
            to Atlas directly; used for logging/debugging.
        element_id:
            Optional ID of the interactive element in the source UIState
            that this action targets.
        action_type:
            Type of interaction (click, key press, etc.).
        label:
            Optional human-readable description (e.g. button text),
            useful for debugging/logging.
        metadata:
            Driver-specific metadata (keys/codes, coordinates, etc.).
    """

    id: str
    element_id: Optional[str]
    action_type: ActionType = ActionType.CLICK
    label: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExplorationDriver(Protocol):
    """
    Protocol that drivers must implement for use with the ExplorationEngine.

    The engine assumes that the driver maintains control of a single
    running instance of the target application/session.
    """

    def capture_state(self) -> UIState:
        """
        Inspect the current UI and return a UIState describing it.

        This should include fingerprints, elements, etc., as far as the
        driver can provide them.
        """
        ...

    def list_actions(self, state: UIState) -> List[CandidateAction]:
        """
        Enumerate candidate actions that can be performed from `state`.

        The returned CandidateAction instances will be passed back to
        `perform_action` by the engine.
        """
        ...

    def perform_action(self, state: UIState, action: CandidateAction) -> None:
        """
        Perform the given action starting from `state`.

        After this call returns, `capture_state()` should reflect the
        resulting UI state (which the engine will then observe).
        """
        ...

    def reset(self) -> UIState:
        """
        Reset the environment to a well-defined starting point.

        This may relaunch the application, navigate to a home screen, etc.
        Returns the resulting UIState.

        The engine typically calls this once at the beginning of a full
        exploration run, and may call it again if something goes wrong.
        """
        ...


# --------------------------------------------------------------------------- #
# Exploration config and state
# --------------------------------------------------------------------------- #


@dataclass
class ExplorationConfig:
    """
    Configuration for the ExplorationEngine.

    Attributes:
        max_depth:
            Maximum depth of DFS exploration (number of actions from the
            starting state). None = unlimited.
        max_states:
            Maximum number of distinct states to discover before stopping.
            None = unlimited.
        max_transitions:
            Maximum number of transitions to record before stopping.
            None = unlimited.
        skip_on_error:
            If True, errors while performing an action are logged and
            exploration continues with the next action.
            If False, errors are propagated and halt exploration.
        log_actions:
            If True, log each action as it is performed.
    """

    max_depth: Optional[int] = 10
    max_states: Optional[int] = 1_000
    max_transitions: Optional[int] = 10_000
    skip_on_error: bool = True
    log_actions: bool = True


@dataclass
class FrontierItem:
    """
    Item in the exploration frontier (DFS stack).

    Attributes:
        state_id:
            ID of the source state (tracked by StateTracker).
        depth:
            Depth of this state from the starting point (0 = root).
    """

    state_id: str
    depth: int


# --------------------------------------------------------------------------- #
# Exploration engine
# --------------------------------------------------------------------------- #


class ExplorationEngine:
    """
    Depth-first exploration engine.

    High-level usage pattern:

        driver = MyDriver(...)
        tracker = StateTracker()
        engine = ExplorationEngine(driver=driver, state_tracker=tracker)

        transitions = engine.explore()

    After `explore()`:

        - `state_tracker` contains all discovered states.
        - `transitions` is a list of Transition objects representing edges.

    Exporting to Atlas (Context, StateRecord, TransitionRecord, etc.) is a
    separate concern handled by the exporter layer.
    """

    def __init__(
        self,
        *,
        driver: ExplorationDriver,
        state_tracker: Optional[StateTracker] = None,
        config: Optional[ExplorationConfig] = None,
        tracker_config: Optional[StateTrackerConfig] = None,
    ) -> None:
        self.driver = driver
        self.state_tracker = state_tracker or StateTracker(tracker_config)
        self.config = config or ExplorationConfig()

        # List of discovered transitions (in observation order)
        self.transitions: List[Transition] = []

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def explore(self) -> List[Transition]:
        """
        Run a depth-first exploration starting from `driver.reset()`.

        Returns:
            List of Transition objects representing discovered edges.
        """
        LOG.info("Exploration started")

        # Initial state
        root_state = self.driver.reset()
        root_state_id, is_new = self.state_tracker.observe_state(root_state)
        if is_new:
            LOG.info("Discovered root state: %s", root_state_id)
        else:
            LOG.info("Root state already known: %s", root_state_id)

        frontier: List[FrontierItem] = [FrontierItem(state_id=root_state_id, depth=0)]

        while frontier:
            item = frontier.pop()
            if self._should_stop():
                LOG.info("Stopping exploration: limits reached")
                break

            tracked = self.state_tracker.get_tracked(item.state_id)
            if tracked is None:
                LOG.warning("Frontier contains unknown state_id=%s; skipping", item.state_id)
                continue

            current_state = tracked.state
            LOG.debug("Exploring state=%s depth=%d", current_state.id, item.depth)

            # Ensure driver is actually at this state.
            # For now we assume linear exploration: driver is already at the
            # last state we produced. More advanced implementations can replay
            # paths or use driver.reset() heuristics.
            #
            # To keep things simple and independent of a replay mechanism,
            # we won't try to "navigate back" here. In a real system, we'd
            # have to coordinate with the driver.

            # Enumerate candidate actions
            actions = self.driver.list_actions(current_state)

            for cand in actions:
                if self._should_stop():
                    break

                # Perform the action and observe resulting state
                try:
                    if self.config.log_actions:
                        LOG.info(
                            "Performing action id=%s type=%s label=%r on state=%s",
                            cand.id,
                            cand.action_type.value,
                            cand.label,
                            current_state.id,
                        )

                    self.driver.perform_action(current_state, cand)
                    new_state = self.driver.capture_state()

                except Exception as exc:  # noqa: BLE001 (explicitly catching for control flow)
                    msg = (
                        f"Error performing action id={cand.id} "
                        f"on state={current_state.id}: {exc}"
                    )
                    if self.config.skip_on_error:
                        LOG.warning(msg)
                        continue
                    raise

                # Register new state with tracker
                new_state_id, is_new_state = self.state_tracker.observe_state(new_state)

                # Record transition
                transition = self._make_transition(
                    source_state_id=current_state.id,
                    target_state_id=new_state_id,
                    candidate=cand,
                )
                self.transitions.append(transition)

                LOG.debug(
                    "Recorded transition %s: %s -> %s",
                    transition.id,
                    transition.source_state_id,
                    transition.target_state_id,
                )

                # If we discovered a new logical state and depth allows, push to frontier
                if is_new_state:
                    next_depth = item.depth + 1
                    if self.config.max_depth is None or next_depth <= self.config.max_depth:
                        LOG.info(
                            "Discovered new state=%s at depth=%d",
                            new_state_id,
                            next_depth,
                        )
                        frontier.append(FrontierItem(state_id=new_state_id, depth=next_depth))
                    else:
                        LOG.debug(
                            "New state=%s exceeds max_depth=%s; not exploring further",
                            new_state_id,
                            self.config.max_depth,
                        )

        LOG.info(
            "Exploration finished: %d states, %d transitions",
            len(self.state_tracker),
            len(self.transitions),
        )
        return self.transitions

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _make_transition(
        self,
        *,
        source_state_id: str,
        target_state_id: str,
        candidate: CandidateAction,
    ) -> Transition:
        """
        Build a Transition object from a CandidateAction.

        The transition ID is generated randomly. Intent is not inferred here;
        it can be attached later by higher-level classifiers.
        """
        action = Action(
            type=candidate.action_type,
            element_id=candidate.element_id,
            raw_input=None,  # could be set by driver if needed
            metadata=dict(candidate.metadata),
        )

        transition_id = uuid.uuid4().hex

        return Transition(
            id=transition_id,
            source_state_id=source_state_id,
            target_state_id=target_state_id,
            action=action,
            intent_id=None,
            confidence=1.0,
            metadata={"candidate_id": candidate.id, "label": candidate.label},
        )

    def _should_stop(self) -> bool:
        """
        Check whether exploration should stop based on configured limits.
        """
        if self.config.max_states is not None and len(self.state_tracker) >= self.config.max_states:
            return True

        if (
            self.config.max_transitions is not None
            and len(self.transitions) >= self.config.max_transitions
        ):
            return True

        return False
