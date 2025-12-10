# Ariane Naming & Structure Contract (for AI Coding)

This document is a **hard canonical reference** for names and structures in the Ariane codebase.

When generating or editing code:

- **Do NOT invent new field/parameter names** if an existing one already exists here.
- **Do NOT change spelling or casing** of any identifier defined here.
- Prefer **reusing** these names and structures over introducing alternatives.

This document is organized by domain:

1. Core models (`common/models`)
2. Atlas schema & storage (`atlas/schema`, `atlas/storage`)
3. Atlas HTTP API shapes (`atlas/api`)
4. Theseus exploration contracts (`theseus/core`, `theseus/drivers`, `theseus/pipelines`)
5. SDK & consumer-facing types (`consumers/sdk`)
6. Standard metadata keys & allowed values
7. Configuration file keys (`config/*.yml`)

---

## 1. Core Models (`common/models`)

### 1.1. `Platform` enum

Location: `common/models/ui_state.py`

```python
class Platform(str, Enum):
    WEB = "web"
    WINDOWS = "windows"
    LINUX = "linux"
    ANDROID = "android"
    MACOS = "macos"
    OTHER = "other"
````

Always use these exact values for platform strings.

---

### 1.2. `BoundingBox`

Location: `common/models/ui_state.py`

Fields:

* `x: int`
* `y: int`
* `width: int`
* `height: int`

Helper:

* `as_tuple() -> tuple[int, int, int, int]`

Do not rename or reorder these fields.

---

### 1.3. `InteractiveElement`

Location: `common/models/ui_state.py`

Fields:

* `id: str`
* `role: str`
* `label: Optional[str]`
* `bounding_box: Optional[BoundingBox]`
* `path: Optional[str]`
* `enabled: bool`
* `visible: bool`
* `metadata: Dict[str, Any]`

Field names are fixed. If additional per-element data is needed, put it inside `metadata`.

---

### 1.4. `UIState`

Location: `common/models/ui_state.py`

Fields:

* `id: str`

* `app_id: str`

* `version: Optional[str]`

* `platform: Platform`

* `locale: Optional[str]`

* `fingerprints: Dict[str, str]`

* `screenshot_ref: Optional[str]`

* `interactive_elements: List[InteractiveElement]`

* `metadata: Dict[str, Any]`

Important conventions:

* `fingerprints` keys **must** be stable, human-readable strings (see section 6).
* `screenshot_ref` is a **reference** (file path, URL, hash) – never raw image bytes.
* Do not add top-level fields to `UIState`; use `metadata` for extras.

Helper methods (do not rename):

* `get_element(element_id: str) -> Optional[InteractiveElement]`
* `find_elements_by_role(role: str) -> List[InteractiveElement]`
* `find_elements_by_label(label: str) -> List[InteractiveElement]`

---

### 1.5. `ActionType` enum

Location: `common/models/transition.py`

Canonical values (do not rename; add new types only if necessary):

* `CLICK = "click"`
* `KEY = "key"`
* `TEXT_INPUT = "text_input"`
* `NAVIGATION = "navigation"`
* `SCROLL = "scroll"`
* `OTHER = "other"`

---

### 1.6. `Action`

Location: `common/models/transition.py`

Fields:

* `type: ActionType`
* `element_id: Optional[str]`
* `raw_input: Optional[str]`
* `metadata: Dict[str, Any]`

Notes:

* `element_id` must match `InteractiveElement.id` in the **source** state.
* Sensitive data must be scrubbed before setting `raw_input`.

---

### 1.7. `IntentCategory` enum

Location: `common/models/intents.py`

Keep existing categories; examples (do not rename):

* `FILE = "file"`
* `EDIT = "edit"`
* `VIEW = "view"`
* `NAVIGATION = "navigation"`
* `EXPORT = "export"`
* `SETTINGS = "settings"`
* `OTHER = "other"`

---

### 1.8. `Intent`

Location: `common/models/intents.py`

Fields:

* `id: str`

  * Stable, lowercase identifier (e.g. `"save"`, `"export_pdf"`).
* `category: IntentCategory`
* `label: str`
* `description: str`
* `synonyms: List[str]`
* `external_refs: Dict[str, str]`

  * e.g. `{"wd": "Q22676"}` for Wikidata.

Do not change field names. New external vocab mappings go into `external_refs`.

---

### 1.9. `Transition`

Location: `common/models/transition.py`

Fields:

* `id: str`
* `source_state_id: str`
* `target_state_id: str`
* `action: Action`
* `intent_id: Optional[str]`
* `confidence: float`
* `metadata: Dict[str, Any]`

Constraints:

* `intent_id` must match `Intent.id` if set.
* `confidence` is in `[0.0, 1.0]` (use `1.0` when unknown).

Helper:

* `attach_intent(intent: Intent, overwrite: bool = True) -> None`

---

### 1.10. Fingerprints (`common/models/fingerprints.py`)

Canonical keys inside `UIState.fingerprints`:

* `"structural"`  → structural hash (tree/DOM/accessibility)
* `"visual"`      → perceptual hash (screenshot-based)
* `"semantic"`    → text/content-based hash

Config class (do not rename fields):

* `FingerprintConfig`:

  * `enable_structural: bool`
  * `enable_visual: bool`
  * `enable_semantic: bool`
  * `structural_key: str` (default `"structural"`)
  * `visual_key: str` (default `"visual"`)
  * `semantic_key: str` (default `"semantic"`)

Engine:

* `FingerprintEngine` with methods:

  * `compute_fingerprints(state: UIState) -> Dict[str, str>`
  * Possibly `compute_structural_fingerprint`, `compute_visual_fingerprint`, etc.

Always store fingerprints under the configured keys; do not invent new top-level fields in `UIState`.

---

## 2. Atlas Schema & Storage

### 2.1. `Context`

Location: `atlas/schema/context.py`

Fields:

* `context_id: str`
* `app_id: str`
* `version: Optional[str]`
* `platform: Optional[str]` (matches `Platform` values)
* `locale: Optional[str]`
* `schema_version: str`
* `created_at: str` (ISO 8601, UTC, `"YYYY-MM-DDTHH:MM:SSZ"`)
* `environment: Dict[str, Any]`
* `metadata: Dict[str, Any]`

Do not add new top-level fields to `Context` – use `metadata`.

---

### 2.2. `StateRecord`

Location: `atlas/schema/state_schema.py`

Fields:

* `context_id: str`

* `state: UIState`

* `discovered_at: str` (ISO 8601, UTC; default: now)

* `is_entry: bool`

* `is_terminal: bool`

* `tags: List[str]`

* `metadata: Dict[str, Any]`

Common metadata keys (section 6):

* `"source"`: `"auto"` or `"human"`
* `"review_status"`: `"pending" | "verified" | "rejected"`
* `"author"`: arbitrary string (user/operator id)
* `"session_id"`: string grouping states/transitions from one recording session

---

### 2.3. `TransitionRecord`

Location: `atlas/schema/transition_schema.py`

Fields:

* `context_id: str`

* `transition: Transition`

* `discovered_at: str` (ISO 8601, UTC; default: now)

* `times_observed: int`

* `metadata: Dict[str, Any]`

Same metadata conventions as `StateRecord`.

---

### 2.4. `GraphStore`

Location: `atlas/storage/graph_store.py`

Important public methods (use these exact names and parameter names):

* `upsert_context(context: Context) -> None`

* `get_context(context_id: str) -> Optional[Context]`

* `list_contexts() -> List[Context]`

* `upsert_state(record: StateRecord) -> None`

* `get_state(context_id: str, state_id: str) -> Optional[StateRecord]`

* `list_states(context_id: str) -> List[StateRecord]`

* `upsert_transition(record: TransitionRecord) -> None`

* `get_transition(context_id: str, transition_id: str) -> Optional[TransitionRecord]`

* `list_transitions(context_id: str) -> List[TransitionRecord]`

* `list_outgoing(context_id: str, state_id: str) -> List[TransitionRecord]`

* `list_incoming(context_id: str, state_id: str) -> List[TransitionRecord]`

* `shortest_path(context_id: str, source_state_id: str, target_state_id: str, max_depth: Optional[int] = None) -> List[TransitionRecord]`

Do not rename methods or parameters; add new methods only if necessary.

---

## 3. Atlas HTTP API Shapes

Base paths and shapes must not be changed.

### 3.1. Health

Endpoint:

* `GET /health`

Response keys:

* `"status": str` (e.g. `"ok"`)
* `"details": { ... }` (optional; implementation-specific)

---

### 3.2. Contexts

Endpoints:

* `GET /contexts`
* `GET /contexts/{context_id}`

`GET /contexts` response:

```json
{
  "contexts": [ <Context dict>, ... ]
}
```

`GET /contexts/{context_id}` response:

```json
{
  "context": <Context dict>
}
```

`Context dict` uses field names from section 2.1.

---

### 3.3. States

Endpoints:

* `GET /contexts/{context_id}/states`
* `GET /contexts/{context_id}/states/{state_id}`

List response:

```json
{
  "states": [ <state_record_dict>, ... ]
}
```

Single response:

```json
{
  "state": <state_record_dict>
}
```

`state_record_dict` keys:

* `"context_id": str`
* `"discovered_at": str`
* `"is_entry": bool`
* `"is_terminal": bool`
* `"tags": [str, ...]`
* `"metadata": { ... }`
* `"state": <ui_state_dict>`

`ui_state_dict` keys mirror `UIState`:

* `"id"`
* `"app_id"`
* `"version"`
* `"platform"`
* `"locale"`
* `"fingerprints"`
* `"screenshot_ref"`
* `"interactive_elements"`
* `"metadata"`

Each `interactive_elements` item:

* `"id"`
* `"role"`
* `"label"`
* `"bounding_box"` (with `"x"`, `"y"`, `"width"`, `"height"`)
* `"path"`
* `"enabled"`
* `"visible"`
* `"metadata"`

---

### 3.4. Transitions

Endpoints:

* `GET /contexts/{context_id}/transitions`
* `GET /contexts/{context_id}/transitions/{transition_id}`
* `GET /contexts/{context_id}/states/{state_id}/outgoing`
* `GET /contexts/{context_id}/states/{state_id}/incoming`

List all:

```json
{
  "transitions": [ <transition_record_dict>, ... ]
}
```

Single:

```json
{
  "transition": <transition_record_dict>
}
```

Outgoing/incoming:

```json
{
  "outgoing": [ <transition_record_dict>, ... ]
}
```

or

```json
{
  "incoming": [ <transition_record_dict>, ... ]
}
```

`transition_record_dict` keys:

* `"context_id": str`
* `"discovered_at": str`
* `"times_observed": int`
* `"metadata": { ... }`
* `"transition": <transition_dict>`

`transition_dict` keys mirror `Transition`:

* `"id"`
* `"source_state_id"`
* `"target_state_id"`
* `"action"` → `"type"`, `"element_id"`, `"raw_input"`, `"metadata"`
* `"intent_id"`
* `"confidence"`
* `"metadata"`

---

### 3.5. Shortest Path

Endpoint:

* `GET /contexts/{context_id}/path?source=<id>&target=<id>[&max_depth=<int>]`

Response keys:

* `"context_id": str`
* `"source_state_id": str`
* `"target_state_id": str`
* `"path": [ <transition_record_dict>, ... ]`

  * `null` if no path exists.

---

### 3.6. Ingest Bundle

Endpoint:

* `POST /ingest/bundle`

Request body:

```json
{
  "context": <Context dict>,
  "states": [ <state_record_dict>, ... ],
  "transitions": [ <transition_record_dict>, ... ]
}
```

Response (canonical keys):

* `"status": "ok"` or `"error"`
* On success:

  * `"context": <Context dict>`
  * `"states": { "count": int }`
  * `"transitions": { "count": int }`
* On error:

  * `"error": str`
  * `"detail": str` (optional)

Do not change key names.

---

## 4. Theseus Exploration Contracts

### 4.1. `ExplorationDriver` Protocol

Location: `theseus/core/exploration_engine.py`

Methods (signatures must be preserved):

* `reset(self) -> UIState`
* `capture_state(self) -> UIState`
* `list_actions(self, state: UIState) -> List[CandidateAction]`
* `perform_action(self, state: UIState, action: CandidateAction) -> None`

Do not rename these methods or parameters.

---

### 4.2. `ExplorationConfig`

Location: `theseus/core/exploration_engine.py`

Fields:

* `max_depth: Optional[int]`
* `max_states: Optional[int]`
* `max_transitions: Optional[int]`
* `skip_on_error: bool`
* `log_actions: bool`

---

### 4.3. `ExplorationEngine`

Location: `theseus/core/exploration_engine.py`

Constructor parameters (names must match):

* `driver: ExplorationDriver`
* `state_tracker: StateTracker`
* `config: ExplorationConfig`

Core method:

* `explore(self) -> List[Transition]`

---

### 4.4. `StateTracker` & `StateTrackerConfig`

Location: `theseus/core/state_tracker.py`

Important fields in `StateTrackerConfig`:

* `prefer_fingerprint_keys: List[str]`
* `allow_id_fallback: bool`
* `auto_generate_ids: bool`

`StateTracker` public methods:

* `register_state(state: UIState) -> UIState`
* `find_existing_state_id(state: UIState) -> Optional[str]`
* `add_transition(transition: Transition) -> None`
* `__len__(self) -> int`  (number of states)

Do not rename or repurpose; add new methods if needed.

---

### 4.5. Exporter (`ExporterConfig`, `Exporter`)

Location: `theseus/core/exporter.py`

`ExporterConfig` fields:

* `app_id: str`
* `version: Optional[str]`
* `platform: Optional[Platform]`
* `locale: Optional[str]`
* `environment: Dict[str, Any]`
* `metadata: Dict[str, Any]`

`Exporter` core methods:

* `build_context(self) -> Context`
* `build_state_records(self) -> List[StateRecord]`
* `build_transition_records(self) -> List[TransitionRecord]`
* `build_bundle(self) -> Dict[str, Any]`

Bundle keys: `"context"`, `"states"`, `"transitions"`.

---

## 5. SDK & Consumer Types

### 5.1. `ContextInfo`

Location: `consumers/sdk/types.py`

Fields:

* `context_id`
* `app_id`
* `version`
* `platform`
* `locale`
* `schema_version`
* `created_at`
* `environment`
* `metadata`

Constructor from API dict:

* `ContextInfo.from_api(payload: Dict[str, Any]) -> ContextInfo`

---

### 5.2. `UIElementHint`

Location: `consumers/sdk/types.py`

Fields:

* `id`
* `role`
* `label`
* `bounding_box`
* `path`
* `enabled`
* `visible`
* `metadata`

Deserializer:

* `UIElementHint.from_api(payload: Dict[str, Any]) -> UIElementHint`

---

### 5.3. `StateView`

Location: `consumers/sdk/types.py`

Fields:

Record-level:

* `context_id`
* `state_id`
* `discovered_at`
* `is_entry`
* `is_terminal`
* `tags`
* `tracker_metadata`

State-level:

* `app_id`
* `version`
* `platform`
* `locale`
* `fingerprints`
* `screenshot_ref`
* `interactive_elements: List[UIElementHint]`
* `state_metadata`

Deserializer:

* `StateView.from_state_record(payload: Dict[str, Any]) -> StateView`

---

### 5.4. `ActionView` & `TransitionView`

Location: `consumers/sdk/types.py`

`ActionView` fields:

* `type: str`
* `element_id: Optional[str]`
* `raw_input: Optional[str]`
* `metadata: Dict[str, Any]`

`TransitionView` fields:

Record-level:

* `context_id`
* `transition_id`
* `discovered_at`
* `times_observed`
* `store_metadata`

Transition-level:

* `source_state_id`
* `target_state_id`
* `action: ActionView`
* `intent_id`
* `confidence`
* `transition_metadata`

Deserializers:

* `ActionView.from_api(payload: Dict[str, Any]) -> ActionView`
* `TransitionView.from_transition_record(payload: Dict[str, Any]) -> TransitionView`

---

### 5.5. `PathView`

Location: `consumers/sdk/types.py`

Fields:

* `context_id`
* `source_state_id`
* `target_state_id`
* `transitions: Optional[List[TransitionView]]`

Deserializer:

* `PathView.from_api(payload: Dict[str, Any]) -> PathView`

Helper:

* `PathView.is_empty(self) -> bool`

---

### 5.6. `AtlasClientConfig`, `AtlasClient`, `AtlasClientError`

Location: `consumers/sdk/client.py`

`AtlasClientConfig` fields:

* `base_url: str`
* `api_key: Optional[str]`
* `api_key_header: str`
* `timeout: int`

`AtlasClient` methods (names and parameters are fixed):

* `health(self) -> Dict[str, Any]`

* `list_contexts(self) -> List[ContextInfo]`

* `get_context(self, context_id: str) -> ContextInfo`

* `list_states(self, context_id: str) -> List[StateView]`

* `get_state(self, context_id: str, state_id: str) -> StateView`

* `list_transitions(self, context_id: str) -> List[TransitionView]`

* `get_transition(self, context_id: str, transition_id: str) -> TransitionView`

* `list_outgoing(self, context_id: str, state_id: str) -> List[TransitionView]`

* `list_incoming(self, context_id: str, state_id: str) -> List[TransitionView]`

* `shortest_path(self, context_id: str, source_state_id: str, target_state_id: str, *, max_depth: Optional[int] = None) -> PathView`

* `ingest_bundle(self, bundle: Dict[str, Any]) -> Dict[str, Any]`

Error type:

* `AtlasClientError(message, status=None, error_detail=None, raw_body=None)`

---

## 6. Metadata Keys & Values (Standardized)

The following keys are **reserved / standardized** in `metadata` fields and should be reused instead of inventing new ones:

### 6.1. Observation source

On `StateRecord.metadata` and `TransitionRecord.metadata`:

* `"source"`:

  * `"auto"`   → produced by automated exploration.
  * `"human"`  → produced by human-guided recording.

### 6.2. Review / quality

On `StateRecord.metadata` and `TransitionRecord.metadata`:

* `"review_status"`:

  * `"pending"`
  * `"verified"`
  * `"rejected"`

Consumers should **prefer** `"verified"` entries when safety matters.

### 6.3. Attribution & grouping

On `StateRecord.metadata` and `TransitionRecord.metadata`:

* `"author"`: string identifying the human or system that produced the record.
* `"session_id"`: string grouping states/transitions from one recording/exploration session.
* `"scan_id"`: optional identifier for automated scans if you need to distinguish runs.

Do not introduce new top-level fields for these; always use `metadata`.

---

## 7. Configuration Keys (`config/*.yml`)

### 7.1. `config/theseus.example.yml`

Top-level key: `theseus`

Sections and keys (names must not change):

* `theseus.app.app_id`

* `theseus.app.version`

* `theseus.app.platform`

* `theseus.app.locale`

* `theseus.driver.type`

* `theseus.driver.web.start_url`

* `theseus.driver.web.browser`

* `theseus.driver.web.options.headless` (example key; options are driver-specific)

* `theseus.exploration.max_depth`

* `theseus.exploration.max_states`

* `theseus.exploration.max_transitions`

* `theseus.exploration.skip_on_error`

* `theseus.exploration.log_actions`

* `theseus.state_tracker.prefer_fingerprint_keys`

* `theseus.state_tracker.allow_id_fallback`

* `theseus.state_tracker.auto_generate_ids`

* `theseus.fingerprint_engine.enable_structural`

* `theseus.fingerprint_engine.enable_visual`

* `theseus.fingerprint_engine.enable_semantic`

* `theseus.fingerprint_engine.structural_key`

* `theseus.fingerprint_engine.visual_key`

* `theseus.fingerprint_engine.semantic_key`

* `theseus.output.mode` (`"filesystem"` or `"atlas"`)

`filesystem` sub-section:

* `theseus.output.filesystem.output_dir`
* `theseus.output.filesystem.use_timestamp_subdirs`

`atlas` sub-section:

* `theseus.output.atlas.base_url`
* `theseus.output.atlas.api_key`
* `theseus.output.atlas.timeout`

---

### 7.2. `config/atlas.example.yml`

Top-level key: `atlas`

Sections:

* `atlas.server.host`

* `atlas.server.port`

* `atlas.server.log_level`

* `atlas.storage.max_contexts`

* `atlas.storage.max_states_per_context`

* `atlas.storage.max_transitions_per_context`

* `atlas.signing.enabled`

* `atlas.signing.default_public_key_path`

* `atlas.signing.trusted_keys[].name`

* `atlas.signing.trusted_keys[].public_key_path`

* `atlas.auth.enabled`

* `atlas.auth.header_name`

* `atlas.auth.optional`

* `atlas.auth.api_keys.<actual_key>.id`

* `atlas.auth.api_keys.<actual_key>.scopes`

* `atlas.auth.api_keys.<actual_key>.metadata`

* `atlas.http.cors.enabled`

* `atlas.http.cors.allowed_origins`

* `atlas.http.cors.allowed_methods`

* `atlas.http.cors.allowed_headers`

---

### 7.3. `config/logging.example.yml`

Standard Python logging dictConfig keys; do not rename:

* `version`
* `disable_existing_loggers`
* `formatters`
* `handlers`
* `loggers`
* `root`

Within loggers, the following logger names are standardized:

* `"theseus"`
* `"theseus.core"`
* `"theseus.drivers"`
* `"atlas"`
* `"atlas.api"`
* `"atlas.storage"`
* `"consumers"`

Use these names when calling `logging.getLogger`.

---

## Final Notes for AI Usage

* Prefer **extending** `metadata` maps over adding new top-level fields anywhere.
* Reuse existing enums and keys (`Platform`, `ActionType`, fingerprint keys, metadata keys).
* For new functionality, **compose** with existing types (`UIState`, `Transition`, `StateRecord`, `TransitionRecord`, `Context`) instead of introducing parallel structures.
* Keep HTTP JSON shapes stable (field names and top-level keys). Any new fields must be **additive** and backwards compatible.

When in doubt, check this document first and adjust code to **match** it rather than diverging.

