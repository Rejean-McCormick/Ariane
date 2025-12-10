# Human-Guided Assistants and Hybrid Mapping

This document describes how Ariane can be used in a **hybrid mode**, where:

- **Theseus** performs automated exploration where possible, and  
- A **human operator** (or assistant) follows **step-by-step textual guidance** derived from Atlas data, and can also **record** workflows that Theseus cannot safely or reliably automate.

This mode is intended for:

- Interfaces with partial or unreliable accessibility support.
- Security-sensitive flows (payments, production systems, administration tools).
- Complex business workflows where human judgment is required.

Any future on-screen overlay or AR client is considered a separate consumer and is out of scope for this document.

---

## 1. Concepts and Data Model

The hybrid mode builds entirely on the existing Atlas primitives:

- **Contexts** (`atlas.schema.context.Context`)  
  Group UI maps by app/version/platform/environment.

- **States** (`atlas.schema.state_schema.StateRecord`)  
  Wrap `UIState` (from `common.models.ui_state`) in Atlas metadata:
  - `context_id`
  - `is_entry` / `is_terminal`
  - `tags` and `metadata` (e.g. `"source": "auto" | "human"`).

- **Transitions** (`atlas.schema.transition_schema.TransitionRecord`)  
  Wrap `Transition` (from `common.models.transition`) with:
  - `context_id`
  - `times_observed` (strength of edge)
  - `metadata` (e.g. `"review_status": "pending" | "verified"`).

- **Intents** (`common.models.intents`)  
  Logical task identifiers (e.g. `"export_pdf"`, `"create_new_project"`), referenced by `Transition.intent_id`.

The hybrid features introduced in this document do **not** change the schema; they rely on:

- Adding **conventions** for `metadata` fields, and  
- Adding **new tools** (recorders and guidance logic) that use the existing Atlas HTTP API and the SDK.

---

## 2. Hybrid Architecture Overview

At a high level there are three layers:

1. **Data Layer – Atlas**  
   - Stores contexts, states, transitions, and intents.
   - Exposes a JSON API for:
     - Listing/inspecting contexts, states, and transitions.
     - Computing shortest paths between states.  
       (via `/contexts/{ctx}/path?source=...&target=...` and the `QueryHandler.shortest_path` helper).

2. **Exploration Layer – Theseus**  
   - Automated crawling using an `ExplorationDriver` (web/desktop/mobile).
   - Pipelines such as `simple_scan` and `batch_scan` export bundles and call Atlas ingest endpoints.

3. **Human-Guided Layer – New**  
   - **Recording tools**: let a human operator perform actions while Theseus captures `StateRecord` and `TransitionRecord` objects and sends them to Atlas.
   - **Guidance tools**: use Atlas’ graph to compute paths and generate **text instructions** like:
     > “Step 2/4 – Click the ‘Export’ button in the File menu.”

The human-guided layer is implemented as regular Python utilities and/or external services built on top of:

- `atlas.api.endpoints.query.QueryHandler`
- `atlas.api.endpoints.ingest.IngestHandler`
- `consumers.sdk.client.AtlasClient` and `consumers.sdk.types.*`

---

## 3. Metadata Conventions for Hybrid Mode

To distinguish automated vs human contributions, and to track quality, Atlas clients should populate the following metadata fields:

### 3.1. Source of observation

On both `StateRecord.metadata` and `TransitionRecord.metadata`:

- `"source": "auto"` – produced by automated Theseus exploration.
- `"source": "human"` – produced by a human-recorded session.

Example (transition record payload):

```json
{
  "context_id": "photoshop-win-en",
  "discovered_at": "2025-03-01T10:00:00Z",
  "times_observed": 1,
  "metadata": {
    "source": "human",
    "author": "assistant-42",
    "session_id": "2025-03-01T09-59-00Z-session-1"
  },
  "transition": {
    "id": "tr_export_pdf_step_2",
    "source_state_id": "state_home",
    "target_state_id": "state_export_dialog",
    "action": { "...": "..." },
    "intent_id": "export_pdf",
    "confidence": 0.95,
    "metadata": {
      "notes": "Verified by human operator"
    }
  }
}
````

### 3.2. Review / verification

For safety-critical flows, a simple review workflow can be expressed via metadata:

* `"review_status": "pending" | "verified" | "rejected"`

Consumers (agents, tools) can then:

* Prefer transitions with `review_status="verified"` when available.
* Fall back to `"pending"` or `"auto"` transitions only if necessary.

---

## 4. Human Recording Tools

### 4.1. Goal

Provide a way for a human operator to:

1. Perform a workflow inside a real application.
2. Have Theseus capture:

   * The sequence of `UIState` instances encountered.
   * The `Transition` objects between them.
3. Export them as a bundle and ingest into Atlas.

This is useful when:

* Automation is blocked (CAPTCHA, 2FA, anti-bot mechanisms).
* The workflow is complex or risky (deletion, payments).
* The interface is partially accessible or highly custom.

### 4.2. Session Recorder (concept)

A **Session Recorder** is a thin wrapper around an `ExplorationDriver`. Conceptually:

* It reuses:

  * `theseus.core.state_tracker.StateTracker`
  * `theseus.core.fingerprint_engine.FingerprintEngine`
  * `theseus.core.exporter.BundleExporter` (or equivalent)
* It adds:

  * A control loop driven by **human actions** instead of automatic exploration.
  * An optional prompt/annotation phase where the operator can:

    * Label the overall intent (`"export_pdf"`, `"change_language_fr"`, etc.).
    * Add notes or tags to the transitions.

A typical flow:

1. Recorder initializes an `ExplorationDriver` (e.g. web/desktop).

2. Recorder captures the **initial state** and marks it as:

   * `is_entry = True`
   * `metadata["source"] = "human"`

3. Loop:

   * Prompt the human to perform the next action in the UI.
   * After they confirm (“done”), the recorder:

     * Captures new `UIState`.
     * Uses the fingerprint engine and tracker to determine source/target IDs.
     * Constructs a `Transition`:

       * `Action.type`: inferred from the driver or human input (click, keypress, etc.).
       * `Action.element_id`: optional element identifier if available.
       * `intent_id`: either:

         * a specific intent if known (e.g. `export_pdf`), or
         * left `None` and filled later in batch.
     * Wraps them into `StateRecord` / `TransitionRecord` with metadata:

       * `source = "human"`
       * `session_id`, `author`, etc.

4. At the end of the workflow, the recorder exports a bundle:

```json
{
  "context": { "...": "..." },
  "states": [ { "...": "..." }, ... ],
  "transitions": [ { "...": "..." }, ... ]
}
```

5. The bundle is ingested via `/ingest/bundle` or using `AtlasClient.ingest_bundle`.

The `ingest` path is already implemented by `IngestHandler.ingest_bundle` in `atlas.api.endpoints.ingest`. The recorder simply needs to shape its output according to the existing `StateRecord.to_dict()` and `TransitionRecord.to_dict()` formats.

---

## 5. Guidance Tools for Human Assistants

### 5.1. Goal

Use Atlas as a **reference** so that an external process can guide a human operator through a workflow using **text instructions**, instead of direct automation or screen overlays.

Given:

* A **current state** on the operator’s machine.
* A **target state** or intent.

The guidance tool should:

1. Match the current state to a known Atlas state.
2. Compute a path from the current state to the target (if one exists).
3. Convert each transition into a readable instruction:

   * “Click the ‘New Project’ button in the toolbar.”
   * “Type the project name in the ‘Name’ field and press Enter.”
4. Ask the operator to execute the step and signal when it’s done.
5. Repeat until:

   * the target is reached, or
   * the path is blocked or diverges (at which point, optional human recording can capture the corrected path).

### 5.2. Matching the current state

A small client running near the human operator (browser extension, desktop helper) is responsible for:

* Capturing the local UI tree (DOM or accessibility tree).
* Computing fingerprints consistent with `common.models.fingerprints.FingerprintConfig`:

  * structural
  * semantic
  * (optional) visual
* Sending a concise payload to a guidance service, e.g.:

```json
{
  "context_id": "photoshop-win-en",
  "fingerprints": {
    "structural": "abc123...",
    "semantic": "def456..."
  }
}
```

A guidance service can then:

1. Query Atlas for states in the context (`GET /contexts/{ctx}/states` or via `AtlasClient.list_states`).
2. Select the **best matching** state using fingerprint similarity (implementation-specific).
3. Treat that state’s `id` as `current_state_id`.

Note: the exact matching algorithm is left to client implementations; Atlas treats fingerprints as opaque strings.

### 5.3. Path computation

Once `current_state_id` and `target_state_id` (or a chosen workflow) are known, the guidance service uses:

* `QueryHandler.shortest_path(...)` or
* `GET /contexts/{ctx}/path?source=...&target=...`

The SDK wrapper `AtlasClient.shortest_path` returns a `PathView` composed of `TransitionView` items, which mirrors the `TransitionRecord` and `Transition` structures.

If no path exists:

* The service can:

  * Ask the human to perform the task manually and record a new path (see Section 4).
  * Or report that the workflow is currently unmapped.

### 5.4. Turning transitions into instructions

Each `Transition` contains:

* `source_state_id`, `target_state_id`
* `Action` (type, element_id, raw_input)
* `intent_id` (optional)
* `metadata` (optional)

Each `UIState` contains:

* `interactive_elements` with:

  * `id`
  * `role`
  * `label`
  * `bounding_box` (optional)
  * `path`
  * `metadata`

Clients can combine these to generate instructions. For example:

1. Fetch the current state (`GET /contexts/{ctx}/states/{state}`).
2. Look up the element referenced by `transition.action.element_id` inside `state.state.interactive_elements`.
3. Build a sentence from:

   * `role` (e.g. “button”, “menu item”, “textbox”).
   * `label` (e.g. “Export”, “File name”).
   * `path` or metadata (e.g. “in the File menu”).

Example instruction structure:

```json
{
  "step_index": 2,
  "step_count": 4,
  "instruction": "Click the 'Export' button in the File menu.",
  "element_hint": {
    "id": "el_btn_export",
    "role": "button",
    "label": "Export",
    "path": "/MenuBar/File/MenuItem[3]"
  }
}
```

The guidance system itself is outside Ariane’s core; it is expected to be implemented in a separate process or library using the SDK.

---

## 6. Example: Minimal Text-Only Guidance Flow

Here is a conceptual end-to-end scenario for a simple human-guided session:

1. **Preparation**

   * Theseus has previously crawled or a human has recorded states/transitions for `"example-web-app"`.
   * Atlas is running at `http://localhost:8080`.
   * A small helper application runs on the operator’s machine, capable of:

     * Capturing the DOM or accessibility tree.
     * Computing fingerprints consistent with Theseus config.

2. **Operator chooses a task**

   * Operator selects: “Export as PDF”.

3. **Guidance service**

   * Receives:

     * `context_id = "example-web-app-en"`
     * `current_fingerprints`
     * `intent_id = "export_pdf"`
   * Maps `current_fingerprints` → best `current_state_id`.
   * Chooses target:

     * Either a known target state for `intent_id`, or a canonical workflow start/goal.
   * Calls `shortest_path` via SDK.

4. **Step-by-step loop**

   * Step 1: guidance service sends:

     > “Step 1/3 – Click the ‘File’ menu at the top-left of the window.”
   * Operator executes the step and clicks “Done” in the helper UI.
   * Helper captures the new state and sends fingerprints back.
   * Guidance service re-aligns to the expected `target_state_id` for step 1 and proceeds to step 2.

5. **Completion**

   * Once the final state is reached, the service confirms the workflow is done.
   * Optionally, the service increments `times_observed` for each transition in the path or logs telemetry elsewhere.

If at any point the UI has changed and the expected state cannot be matched, the system can:

* Fall back to human recording mode to capture the new path, then:

  * Ingest it into Atlas.
  * Mark the old transitions as stale via metadata.

---

## 7. Relationship to Future Overlay Clients

This document focuses on **data structures** and **text-based guidance**.

If a future project decides to implement a visual overlay client (heads-up display, AR, etc.), it can:

* Use the **same state and transition data** from Atlas.
* Use the **same guidance logic**, but render:

  * Highlights on screen,
  * Click-through masks,
  * Progress indicators.

The current design keeps the overlay out of scope and treats it as another consumer of the Atlas API, alongside text-only guidance tools and agents.


