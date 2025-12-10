# Guidance Client (Text + Optional Overlay) — Future Design

Status: **future work / not implemented**  
Scope: **consumer of Atlas data**, no UI crawling or recording.

The Guidance Client is a future component that uses Ariane’s graph data to guide a **human user** through software workflows.

It is designed to:

- Provide **textual step-by-step guidance** (e.g. “Click the **Export** button in the top menu”).
- Optionally provide a **visual overlay** that highlights the target UI element when the platform allows it.

The Guidance Client does **not** explore UIs by itself. It consumes:

- Automatically mapped paths (Theseus),
- Human-recorded workflows (SessionRecorder),
- Stored and served by Atlas and accessed via the SDK.

---

## 1. Supported Scope and Limitations

The Guidance Client is only intended for apps where guidance is realistic or works with minor caveats:

### 1.1 Primary target environments

- **Web apps with DOM/ARIA**
  - Browsers expose DOM + layout + accessibility roles.
  - Guidance can:
    - Resolve current state via fingerprints.
    - Compute paths via Atlas.
    - Show textual instructions, and optionally draw an overlay via a browser extension.

- **Desktop apps with usable accessibility APIs**
  - Windows (UIA), Linux (AT-SPI), macOS (AX).
  - Guidance can:
    - Inspect controls,
    - Use bounding boxes for elements,
    - Provide text guidance and potentially screen overlays.

- **Mobile apps with accessibility trees**
  - Android, iOS.
  - Guidance can:
    - Use accessibility nodes as elements,
    - Provide textual steps,
    - Potentially overlay hints via native UI.

### 1.2 Partial or limited environments

- Apps with incomplete/broken accessibility:
  - Guidance may rely more on text, with approximate overlay.
- Highly dynamic/A/B-tested UIs:
  - Variants must be modeled as multiple states/paths in Atlas.
- Strongly locked-down or unusual apps:
  - Guidance may be text-only, or not supported.

The Guidance Client **does not aim** to support every possible application. It focuses on environments where accessibility and inspection are realistically available, plus a “long tail” where small gaps can be bridged with human-recorded paths and minor caveats.

---

## 2. Component Overview

The Guidance Client is a **consumer layer** on top of existing Ariane components:

- **Mapping**: Theseus + human SessionRecorder → states & transitions.
- **Storage/API**: Atlas → contexts, states, transitions, shortest paths.
- **SDK**: `AtlasClient` + SDK types → convenience for consumers.
- **Guidance Client** (future): text guidance + optional overlay.

### 2.1 Files in this design

Planned implementation files (future):

- Core guidance models and engine:
  - `consumers/guidance/models.py`
  - `consumers/guidance/probe_interface.py`
  - `consumers/guidance/matching.py`
  - `consumers/guidance/engine.py`
  - `consumers/guidance/__init__.py`
- CLI example (text-only guidance):
  - `consumers/examples/cli-guidance-example.py`
- This design document:
  - `docs/future/guidance_client.md`

---

## 3. Local UI Probes

A **GuidanceProbe** is responsible for observing the current UI on the user’s machine.

Defined in:

- `consumers/guidance/probe_interface.py`

Key types:

- `LocalUISnapshot`
  - `context_hint: Optional[str]`
  - `fingerprints: Dict[str, str]` — e.g. `"structural"`, `"semantic"`, `"visual"`.
  - `elements: List[LocalElementSnapshot]`
  - `metadata: Dict[str, Any]`

- `LocalElementSnapshot`
  - `local_id: Optional[str]`
  - `role: Optional[str]` — e.g. `"button"`, `"link"`.
  - `label: Optional[str]`
  - `bounding_box: Optional[BoundingBoxSnapshot]`
  - `path: Optional[str]` — local tree path (DOM, AX, etc.).
  - `enabled: Optional[bool]`
  - `visible: Optional[bool]`
  - `metadata: Dict[str, Any]`

- `GuidanceProbe` (abstract)
  - `capture_snapshot() -> LocalUISnapshot`

- `NullProbe`
  - Trivial probe that returns a preconfigured `LocalUISnapshot` (used for tests/CLI example).
  - No actual UI inspection.

Platform-specific probes (browser, desktop, mobile) would live in separate modules and implement `GuidanceProbe`. They are explicitly **out of scope** for the core library and this document.

---

## 4. State Matching

To guide the user, the engine must map a `LocalUISnapshot` to a known `StateView` from Atlas.

Defined in:

- `consumers/guidance/matching.py`
- Uses models from `consumers/guidance/models.py`
- Uses SDK types from `consumers/sdk/types.py`

### 4.1 Configuration

`MatchingConfig`:

- `structural_weight: float = 0.6`
- `semantic_weight: float = 0.3`
- `visual_weight: float = 0.1`
- `min_score: float = 0.0`
- `require_fingerprint_overlap: bool = False`

### 4.2 Result types

- `StateMatchDetails`
  - `structural_score: Optional[float]`
  - `semantic_score: Optional[float]`
  - `visual_score: Optional[float]`
  - `combined_score: Optional[float]`
  - `metadata: Dict[str, Any]` (e.g. per-fingerprint scores)

- `StateMatchResult`
  - `state: StateView`
  - `score: float` (normalized [0.0, 1.0])
  - `details: Optional[StateMatchDetails]`

### 4.3 Public API

- `score_state_match(snapshot, state, config) -> Optional[StateMatchResult]`
- `match_states(snapshot, candidates, config) -> List[StateMatchResult]`  
  Sorted by score descending.
- `best_match(snapshot, candidates, config, min_score) -> Optional[StateMatchResult]`

Default similarity behavior:

- Structural: equality-based per fingerprint key, averaged.
- Semantic: Jaccard similarity over tokenized labels from elements.
- Visual: equality on `"visual"` fingerprint (placeholder).

These heuristics are deliberately simple and safe to extend later.

---

## 5. Guidance Models

Defined in:

- `consumers/guidance/models.py`

### 5.1 Goals

- `GoalType`:
  - `INTENT`
  - `TARGET_STATE`
  - `WORKFLOW` (future)

- `GuidanceGoal`:
  - `goal_type: GoalType`
  - `intent_id: Optional[str]`
  - `target_state_id: Optional[str]`
  - `workflow_id: Optional[str]`
  - `label: Optional[str]`
  - `description: Optional[str]`
  - `metadata: Dict[str, Any]`

### 5.2 Guidance steps

- `GuidanceStepKind`:
  - `ACTION` — “click this button”.
  - `INFO` — informational.
  - `COMPLETE` — goal reached.
  - `ERROR` — cannot proceed.

- `GuidanceStep`:
  - `step_index: int`
  - `step_count: int`
  - `kind: GuidanceStepKind`
  - `instruction: str` — main textual instruction.
  - `context_id: Optional[str]`
  - `source_state_id: Optional[str]`
  - `target_state_id: Optional[str]`
  - `transition: Optional[TransitionView]`
  - `element_hint: Optional[UIElementHint]` — used by overlay if available.
  - `notes: Optional[str]`
  - `blocking: bool` — if true, UI may restrict other actions.
  - `metadata: Dict[str, Any]`

### 5.3 Plans and sessions

- `GuidancePlanStatus`:
  - `READY`
  - `FAILED`
  - `PARTIAL`

- `GuidancePlan`:
  - `context_id: str`
  - `goal: GuidanceGoal`
  - `source_state_id: str`
  - `target_state_id: str`
  - `status: GuidancePlanStatus`
  - `steps: List[GuidanceStep]`
  - `path_view: Optional[PathView]`
  - `metadata: Dict[str, Any]`

- `SessionStatus`:
  - `NOT_STARTED`
  - `RUNNING`
  - `COMPLETED`
  - `FAILED`
  - `CANCELLED`

- `GuidanceSessionState`:
  - `context_id: str`
  - `plan: GuidancePlan`
  - `current_step_index: int`
  - `current_state: Optional[StateView]`
  - `status: SessionStatus`
  - `metadata: Dict[str, Any]`
  - `current_step() -> Optional[GuidanceStep]`
  - `is_finished() -> bool`

---

## 6. Guidance Engine

Defined in:

- `consumers/guidance/engine.py`

### 6.1 Configuration

- `GuidanceEngineConfig`:
  - `matching_config: MatchingConfig`
  - `max_path_depth: Optional[int]` — limit for shortest-path queries.

- `GuidanceEngineError` — for configuration/goal issues.

### 6.2 Core API

`GuidanceEngine`:

- Fields:
  - `client: AtlasClient`
  - `probe: GuidanceProbe`
  - `config: GuidanceEngineConfig`

- Methods:

  - `resolve_current_state(context_id, snapshot=None, min_score=None) -> Optional[StateMatchResult]`
    - Captures snapshot if not provided.
    - Matches to candidate `StateView`s in the context using matching config.

  - `build_plan(context_id, goal, snapshot=None) -> GuidancePlan`
    - Validates context.
    - Resolves current state via probe/snapshot.
    - For `GoalType.TARGET_STATE`:
      - Calls `_build_path_steps()` and uses Atlas `shortest_path`.
      - Returns `GuidancePlanStatus.READY` or `FAILED`.
    - For `GoalType.INTENT` / `GoalType.WORKFLOW` (current design):
      - Returns `GuidancePlanStatus.PARTIAL` with an informational step.
      - External logic must map intent/workflow to a target state.

  - `_build_path_steps(context_id, source_state_id, target_state_id, goal)`
    - If source == target:
      - Returns READY plan with a single COMPLETE step.
    - Otherwise:
      - Calls `client.shortest_path(...)`.
      - Converts `TransitionView` objects to `GuidanceStep`s.
      - On failure: returns plan with an ERROR step.

  - `start_session(context_id, goal, snapshot=None) -> GuidanceSessionState`
    - Builds a plan and creates a `GuidanceSessionState`.
    - Initial `current_step_index` and `status` depend on plan status.

  - `advance_session(session, snapshot=None) -> GuidanceSessionState`
    - Moves `current_step_index` forward by one.
    - Marks session `COMPLETED` when steps are exhausted.
    - Does **not** currently re-validate state on each step; this is left to higher-level controllers.

---

## 7. Text-Only CLI Example

Defined in:

- `consumers/examples/cli-guidance-example.py`

Purpose:

- Demonstrate the Guidance Client in **text mode only**.
- No real probe integration; it uses a `NullProbe` and synthetic snapshot.

Behavior:

1. Connect to Atlas using `AtlasClient`.
2. Fetch context and states.
3. Given:
   - `--context-id`
   - `--current-state-id`
   - `--target-state-id`
4. Build a synthetic `LocalUISnapshot` whose fingerprints match the chosen “current” state.
5. Start a session with:
   - `GoalType.TARGET_STATE` and the provided target state ID.
6. Iterate through `GuidanceStep`s:
   - Print `kind`, `instruction`, and any `element_hint` info.
   - Wait for user to press Enter before advancing.
   - Stop on `ERROR` or `COMPLETE`.

This example is intended for **testing the logic** of the engine and models without any real UI integration.

---

## 8. Overlay Guidance (Future)

Overlay rendering is a **future, optional enhancement**.

Design intent:

- Use `GuidanceStep.element_hint` (bounding box, label, role, etc.) to draw hints **on top of** the target application.
- Behavior patterns:
  - **Spotlight**:
    - Dim the rest of the screen/window.
    - Highlight the target element’s bounding box.
  - **Step counter**:
    - Visual “Step N of M” badge.
  - **Guardrails** (optional):
    - Warn on clicks outside the suggested region in critical flows.

Implementation considerations:

- Web overlay:
  - Likely via browser extension or injected script, using the DOM and CSS.
- Desktop overlay:
  - Transparent top-level window + OS accessibility coordinates.
- Mobile overlay:
  - Platform-specific overlay mechanisms.

Privacy and security:

- Overlay and probing must remain **local-first**:
  - No raw screenshots or keystrokes sent to remote services by default.
  - No automatic session recording.
- Any telemetry or analytics must be **explicit opt-in**.

Overlay code is intentionally **not part of this repo design** yet. The Guidance Client models/engine are designed so that multiple overlay or presentation implementations can be built on top later without changing the core.

---

## 9. Relationship to Hybrid Mapping

The Guidance Client complements the existing hybrid mapping strategy:

- **Automated mapping (Theseus)**:
  - Covers straightforward, well-behaved parts of UIs.
- **Human recording (SessionRecorder)**:
  - Captures complex or fragile workflows.
- **Atlas**:
  - Stores both, with metadata (e.g. `source: "auto"` vs `source: "human"`, `review_status`).

Guidance behavior:

- Prefer transitions/states with:
  - `metadata["source"] == "human"` when possible.
  - `metadata["review_status"] == "verified"` for safety-critical flows.
- When guidance fails:
  - Human operators can record new/updated workflows.
  - Re-ingesting them improves future guidance.

---

## 10. Summary

The Guidance Client is a **future consumer** of Ariane’s UI graph:

- Text-first, overlay-optional.
- Works only where accessibility/inspection is realistic or needs only minor caveats.
- Built around:
  - `GuidanceProbe` + `LocalUISnapshot`
  - Matching logic → `StateMatchResult`
  - Guidance models → `GuidancePlan`, `GuidanceStep`, `GuidanceSessionState`
  - `GuidanceEngine` to orchestrate everything using Atlas and the SDK.

Implementation of actual UI probes and overlay rendering is intentionally kept **outside** the core library and can be developed independently when the rest of the stack is stable.
