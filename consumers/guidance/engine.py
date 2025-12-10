"""
Guidance engine for the Guidance Client.

This module ties together:

- A local UI probe (GuidanceProbe),
- The Atlas SDK client (AtlasClient),
- Matching logic (matching.py),
- Guidance data models (models.py),

to produce step-by-step guidance plans and sessions.

The engine:

1) Resolves the current UI state by matching a LocalUISnapshot to
   known StateView objects in a given context.

2) Builds a GuidancePlan from the current state towards a goal:
   - TARGET_STATE goals are fully supported (shortest_path).
   - INTENT / WORKFLOW goals are currently left as partial plans
     and require an external resolver to map them to target states.

3) Manages a lightweight GuidanceSessionState to track progress
   through a plan.

The engine itself is *pure logic*: it does not perform any UI drawing
or user interaction. Presentation layers (CLI, GUI, overlay) consume
the GuidanceStep objects it produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from consumers.guidance.matching import MatchingConfig, best_match
from consumers.guidance.models import (
    GoalType,
    GuidanceGoal,
    GuidancePlan,
    GuidancePlanStatus,
    GuidanceSessionState,
    GuidanceStep,
    GuidanceStepKind,
    SessionStatus,
    StateMatchResult,
)
from consumers.guidance.probe_interface import GuidanceProbe, LocalUISnapshot, ProbingError
from consumers.sdk.client import AtlasClient
from consumers.sdk.types import PathView, StateView, TransitionView, UIElementHint


class GuidanceEngineError(Exception):
    """
    Raised when the guidance engine cannot proceed due to invalid
    configuration, missing data, or unresolved goals.
    """


@dataclass
class GuidanceEngineConfig:
    """
    Configuration for the GuidanceEngine.

    - matching_config:
        Controls how snapshots are matched to known states.
    - max_path_depth:
        Optional bound for shortest_path queries into Atlas.
    """

    matching_config: MatchingConfig = field(default_factory=MatchingConfig)
    max_path_depth: Optional[int] = None


@dataclass
class GuidanceEngine:
    """
    High-level orchestration for building plans and sessions.

    Typical usage:

        engine = GuidanceEngine(client=atlas_client, probe=my_probe)

        # Build a one-shot plan from current UI towards a target state.
        plan = engine.build_plan(
            context_id="ctx-1",
            goal=GuidanceGoal(
                goal_type=GoalType.TARGET_STATE,
                target_state_id="state_target",
            ),
        )

        # Or manage an interactive session:
        session = engine.start_session(context_id, goal)
        # Show session.current_step() via a presentation layer.
        session = engine.advance_session(session)
    """

    client: AtlasClient
    probe: GuidanceProbe
    config: GuidanceEngineConfig = field(default_factory=GuidanceEngineConfig)

    # ------------------------------------------------------------------ #
    # State resolution
    # ------------------------------------------------------------------ #

    def resolve_current_state(
        self,
        context_id: str,
        snapshot: Optional[LocalUISnapshot] = None,
        min_score: Optional[float] = None,
    ) -> Optional[StateMatchResult]:
        """
        Capture (or accept) a snapshot and resolve it to a StateView.

        Args:
            context_id:
                Atlas context to search in.
            snapshot:
                Optional LocalUISnapshot; if None, capture from probe.
            min_score:
                Optional minimum score override for best_match.

        Returns:
            StateMatchResult for the best candidate, or None if no
            satisfactory match is found.
        """
        if snapshot is None:
            snapshot = self.probe.capture_snapshot()

        # Fetch candidate states from Atlas.
        states = self.client.list_states(context_id)

        if not states:
            return None

        # Use matching logic to pick the best candidate.
        match = best_match(
            snapshot=snapshot,
            candidates=states,
            config=self.config.matching_config,
            min_score=min_score,
        )
        return match

    # ------------------------------------------------------------------ #
    # Plan construction
    # ------------------------------------------------------------------ #

    def build_plan(
        self,
        context_id: str,
        goal: GuidanceGoal,
        snapshot: Optional[LocalUISnapshot] = None,
    ) -> GuidancePlan:
        """
        Build a GuidancePlan from the current UI state towards a goal.

        Currently:

        - GoalType.TARGET_STATE:
            Fully supported using Atlas shortest_path.
        - GoalType.INTENT and GoalType.WORKFLOW:
            Produce a PARTIAL plan with an informational step and no
            path computation. An external component (agent, human, or
            future resolver) should map these to a target_state_id and
            rebuild the plan.

        Args:
            context_id:
                Atlas context id.
            goal:
                GuidanceGoal describing user intent.
            snapshot:
                Optional LocalUISnapshot; if None, capture from probe.

        Returns:
            GuidancePlan (status READY, PARTIAL, or FAILED).
        """
        # Sanity check: ensure context exists.
        ctx = self.client.get_context(context_id)
        if ctx is None:
            raise GuidanceEngineError(f"Context '{context_id}' not found")

        # Resolve current state.
        if snapshot is None:
            snapshot = self.probe.capture_snapshot()

        match = self.resolve_current_state(context_id, snapshot=snapshot)
        if match is None:
            # No match found: produce a FAILED plan with an error step.
            empty_goal = goal
            plan = GuidancePlan(
                context_id=context_id,
                goal=empty_goal,
                source_state_id="",
                target_state_id="",
                status=GuidancePlanStatus.FAILED,
                steps=[],
                path_view=None,
                metadata={
                    "reason": "no_state_match",
                },
            )
            error_step = GuidanceStep(
                step_index=0,
                step_count=1,
                kind=GuidanceStepKind.ERROR,
                instruction=(
                    "Unable to match the current UI to any known state in this context. "
                    "The map may be incomplete or out of date."
                ),
                context_id=context_id,
                notes="No StateView exceeded the minimum matching score.",
                blocking=False,
            )
            plan.steps.append(error_step)
            return plan

        current_state_view: StateView = match.state
        current_state_id = current_state_view.state_id

        # Resolve target state based on goal type.
        target_state_id: Optional[str] = None
        plan_status: GuidancePlanStatus
        path_view: Optional[PathView] = None
        steps: list[GuidanceStep] = []

        if goal.goal_type == GoalType.TARGET_STATE:
            if not goal.target_state_id:
                raise GuidanceEngineError(
                    "TARGET_STATE goal requires target_state_id to be set"
                )
            target_state_id = goal.target_state_id
            plan_status, path_view, steps = self._build_path_steps(
                context_id=context_id,
                source_state_id=current_state_id,
                target_state_id=target_state_id,
                goal=goal,
            )

        elif goal.goal_type in (GoalType.INTENT, GoalType.WORKFLOW):
            # For now, intents and workflows are not resolved automatically.
            # Produce a PARTIAL plan with an informational step.
            target_state_id = current_state_id
            plan_status = GuidancePlanStatus.PARTIAL
            info_instruction = (
                "Guidance by intent/workflow is not yet resolved in this engine. "
                "An external component must map the goal to a target state and "
                "rebuild the plan."
            )
            steps.append(
                GuidanceStep(
                    step_index=0,
                    step_count=1,
                    kind=GuidanceStepKind.INFO,
                    instruction=info_instruction,
                    context_id=context_id,
                    source_state_id=current_state_id,
                    target_state_id=target_state_id,
                    notes="INTENT/WORKFLOW resolution not implemented.",
                    blocking=False,
                )
            )

        else:
            raise GuidanceEngineError(f"Unsupported goal_type: {goal.goal_type}")

        plan = GuidancePlan(
            context_id=context_id,
            goal=goal,
            source_state_id=current_state_id,
            target_state_id=target_state_id or current_state_id,
            status=plan_status,
            steps=steps,
            path_view=path_view,
            metadata={
                "initial_match_score": match.score,
                "current_state_id": current_state_id,
            },
        )
        return plan

    def _build_path_steps(
        self,
        context_id: str,
        source_state_id: str,
        target_state_id: str,
        goal: GuidanceGoal,
    ) -> tuple[GuidancePlanStatus, Optional[PathView], list[GuidanceStep]]:
        """
        Internal helper to query Atlas for a path and convert it into
        GuidanceStep objects.
        """
        # Short-circuit: already at the target.
        if source_state_id == target_state_id:
            # No transitions are needed; plan is trivially complete.
            steps: list[GuidanceStep] = [
                GuidanceStep(
                    step_index=0,
                    step_count=1,
                    kind=GuidanceStepKind.COMPLETE,
                    instruction="You are already at the target state.",
                    context_id=context_id,
                    source_state_id=source_state_id,
                    target_state_id=target_state_id,
                    notes=None,
                    blocking=False,
                )
            ]
            return GuidancePlanStatus.READY, None, steps

        # Ask Atlas for the shortest path.
        path_view = self.client.shortest_path(
            context_id=context_id,
            source_state_id=source_state_id,
            target_state_id=target_state_id,
            max_depth=self.config.max_path_depth,
        )

        if path_view is None or not path_view.transitions:
            # No path found.
            steps: list[GuidanceStep] = [
                GuidanceStep(
                    step_index=0,
                    step_count=1,
                    kind=GuidanceStepKind.ERROR,
                    instruction=(
                        "No path found between the current state and the target. "
                        "The map may be incomplete or the workflow has changed."
                    ),
                    context_id=context_id,
                    source_state_id=source_state_id,
                    target_state_id=target_state_id,
                    notes=None,
                    blocking=False,
                )
            ]
            return GuidancePlanStatus.FAILED, path_view, steps

        # Build ACTION steps from transitions.
        steps: list[GuidanceStep] = []
        total_steps = len(path_view.transitions)

        for idx, tr in enumerate(path_view.transitions):
            step = self._transition_to_step(
                context_id=context_id,
                transition_view=tr,
                step_index=idx,
                step_count=total_steps,
            )
            steps.append(step)

        return GuidancePlanStatus.READY, path_view, steps

    def _transition_to_step(
        self,
        context_id: str,
        transition_view: TransitionView,
        step_index: int,
        step_count: int,
    ) -> GuidanceStep:
        """
        Convert a TransitionView into a user-facing GuidanceStep.

        This implementation intentionally stays generic and relies only
        on fields that are expected to exist on TransitionView and
        UIElementHint. Presentation-specific text generation can be
        refined later.
        """
        source_state_id = transition_view.source_state_id
        target_state_id = transition_view.target_state_id

        # Best-effort element hint extraction.
        element_hint: Optional[UIElementHint] = getattr(
            transition_view, "element_hint", None
        )

        # Derive a basic instruction.
        if element_hint and element_hint.label:
            role = element_hint.role or "control"
            instruction = f"Click the “{element_hint.label}” {role}."
        else:
            # Generic fallback.
            instruction = "Perform the next action in the workflow."

        return GuidanceStep(
            step_index=step_index,
            step_count=step_count,
            kind=GuidanceStepKind.ACTION,
            instruction=instruction,
            context_id=context_id,
            source_state_id=source_state_id,
            target_state_id=target_state_id,
            transition=transition_view,
            element_hint=element_hint,
            notes=None,
            blocking=False,
        )

    # ------------------------------------------------------------------ #
    # Session helpers
    # ------------------------------------------------------------------ #

    def start_session(
        self,
        context_id: str,
        goal: GuidanceGoal,
        snapshot: Optional[LocalUISnapshot] = None,
    ) -> GuidanceSessionState:
        """
        Build a guidance plan and wrap it in a GuidanceSessionState.

        The session starts at step 0 if the plan has actionable steps
        and status READY; otherwise, the session is immediately in a
        terminal state (COMPLETED/FAILED) based on the plan.
        """
        if snapshot is None:
            snapshot = self.probe.capture_snapshot()

        match = self.resolve_current_state(context_id, snapshot=snapshot)
        # Note: build_plan will recompute resolve_current_state internally
        # if we pass snapshot=None. To keep the session state aligned
        # with the plan's initial metadata, we use the same snapshot.
        plan = self.build_plan(context_id=context_id, goal=goal, snapshot=snapshot)

        if match is None:
            # Already handled as FAILED in build_plan, but we keep session
            # metadata explicit.
            session_status = SessionStatus.FAILED
            current_state_view: Optional[StateView] = None
            current_step_index = -1
        else:
            current_state_view = match.state
            if plan.status == GuidancePlanStatus.READY and plan.steps:
                session_status = SessionStatus.RUNNING
                current_step_index = 0
            elif plan.status == GuidancePlanStatus.READY and not plan.steps:
                # Trivial plan (already at target).
                session_status = SessionStatus.COMPLETED
                current_step_index = -1
            elif plan.status == GuidancePlanStatus.FAILED:
                session_status = SessionStatus.FAILED
                current_step_index = 0 if plan.steps else -1
            else:
                # PARTIAL or other.
                session_status = SessionStatus.RUNNING
                current_step_index = 0 if plan.steps else -1

        session = GuidanceSessionState(
            context_id=context_id,
            plan=plan,
            current_step_index=current_step_index,
            current_state=current_state_view,
            status=session_status,
            metadata={},
        )
        return session

    def advance_session(
        self,
        session: GuidanceSessionState,
        snapshot: Optional[LocalUISnapshot] = None,
    ) -> GuidanceSessionState:
        """
        Advance the session to the next step.

        This is a minimal implementation:

        - It does not re-validate that the user performed the previous
          step correctly.
        - It does not recompute the current state from a new snapshot.

        Those behaviors can be layered on top in more advanced
        session controllers.

        Args:
            session:
                The current GuidanceSessionState.
            snapshot:
                Optional updated snapshot; currently unused but accepted
                for future extensions.

        Returns:
            A new GuidanceSessionState (sessions are treated as immutable
            from the engine's perspective).
        """
        if session.is_finished():
            return session

        # Optionally update current_state from snapshot, if desired in future.
        new_current_state = session.current_state
        if snapshot is not None:
            # Example future behavior:
            # match = self.resolve_current_state(session.context_id, snapshot=snapshot)
            # if match is not None:
            #     new_current_state = match.state
            new_current_state = session.current_state

        next_index = session.current_step_index + 1
        if next_index >= len(session.plan.steps):
            # No more steps; mark as completed if not already terminal.
            new_status = (
                session.status
                if session.is_finished()
                else SessionStatus.COMPLETED
            )
            return GuidanceSessionState(
                context_id=session.context_id,
                plan=session.plan,
                current_step_index=session.current_step_index,
                current_state=new_current_state,
                status=new_status,
                metadata=dict(session.metadata),
            )

        return GuidanceSessionState(
            context_id=session.context_id,
            plan=session.plan,
            current_step_index=next_index,
            current_state=new_current_state,
            status=session.status,
            metadata=dict(session.metadata),
        )


__all__ = [
    "GuidanceEngineError",
    "GuidanceEngineConfig",
    "GuidanceEngine",
]
