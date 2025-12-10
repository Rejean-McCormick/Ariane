# Ariane

Ariane is a semantic infrastructure project that treats user interfaces as data.

It defines a universal graph model for software UIs—screens, controls, and the actions that connect them—and provides tools to explore real applications and store that graph so external systems (such as AI agents or automation tools) can query it as a reference when guiding users through software.

Ariane itself is **not** a help overlay or assistant. It is the underlying map.

> **Core idea:** “UI as data” – represent any interface as a graph of states and transitions, independent of platform, styling, or branding.

---

## Components

Ariane is implemented as three cooperating subsystems:

### Theseus – Exploration Engine

Theseus is a platform-agnostic exploration engine that inspects real software and extracts a graph of:

- **States** – distinct UI configurations (screens, dialogs, menus, etc.).
- **Transitions** – user actions that move from one state to another (clicks, key presses, menu selections, etc.).

It operates through pluggable drivers (web, desktop, mobile) that normalize different accessibility/UI APIs into a common internal representation. Theseus supports:

- **Automated exploration** where interfaces are accessible and safe to probe.
- **Human-guided recording** where a human operator performs actions and Theseus records the resulting states and transitions as data.

Core code lives under:

- `common/models/` – shared data models (UIState, Transition, fingerprints, intents).
- `theseus/core/` – state tracking, fingerprinting, exploration, export pipeline.
- `theseus/drivers/` – driver helpers for web/desktop/mobile.
- `theseus/pipelines/` – simple and batch scan pipelines plus sandbox utilities.

### Atlas – UI Graph and Ontology

Atlas is the storage and semantic layer that persists the UI graph produced by Theseus. It provides:

- A **graph model** of states and transitions per application context.
- A **core schema** for representing UI elements, actions, and app metadata.
- An **ontology vocabulary** for common UI patterns and semantic intents (e.g. “Save”, “Export”, “Create”).
- Optional **signing** and **API-key auth** for ingestion and query endpoints.

Core code lives under:

- `atlas/schema/` – context, state, transition, ontology definitions.
- `atlas/storage/` – in-memory graph store and signing helpers.
- `atlas/api/` – HTTP server, auth, ingest and query endpoints.

Atlas is designed as a small, dependency-light reference implementation. For production-scale deployments, the same API and schema can be reimplemented on top of a persistent database or graph engine.

### Consumers – SDK and Examples

The `consumers` directory contains client-side tooling that treats Atlas as a data source:

- **Python SDK**
  - `consumers/sdk/types.py` – typed views of contexts, states, transitions, paths, and error payloads.
  - `consumers/sdk/client.py` – a small HTTP client for Atlas (health checks, listing contexts, querying states/transitions, computing shortest paths, ingesting bundles).

- **Examples**
  - `consumers/examples/cli-agent-example.py` – a minimal CLI that calls Atlas and prints paths and graph information.
  - `consumers/examples/notebook.ipynb` – a Jupyter notebook for interactive exploration of a running Atlas instance.

These are intended as references for building:

- AI agents that plan workflows over existing UIs.
- automation / testing tools that need declarative UI workflows.
- analysis tools that inspect UI structure and complexity.

---

## Hybrid mapping: automation + human-in-the-loop

Ariane is designed for **hybrid mapping**:

- **Automated exploration** with Theseus:
  - covers standards-based, accessibility-friendly UIs.
- **Human-guided recording**:
  - a human operator performs actions in a real application;
  - Theseus (or a separate recorder) captures before/after UI states and the transition between them;
  - the resulting states and transitions are ingested into Atlas.

Both automated and human-recorded data share the same model:

- `StateRecord.metadata["source"] = "auto" | "human"`
- `TransitionRecord.metadata["source"] = "auto" | "human"`
- optional quality flags (e.g. `review_status = "pending" | "verified"`).

External systems can:

- Prefer human-verified or reviewed paths for safety-critical workflows.
- Fall back to automatically discovered edges when needed.

A text-based or UI-based assistant can then:

1. Recognize the current UI state by matching fingerprints or structure to Atlas.
2. Ask Atlas for a path from the current state to a desired goal state or intent.
3. Turn each transition into a step-by-step instruction for a human operator (or for a separate automation layer).

Any UI overlay or AR-style client that uses Ariane data is considered an **external consumer** and is out of scope for this repository, but may be built later on top of the existing API and graph.

---

## Repository layout

High-level layout of this repository:

- `README.md`  
  High-level description, components, and repository structure.

- `common/`  
  Shared models and types used by Theseus and Atlas:
  - `models/ui_state.py`
  - `models/transition.py`
  - `models/fingerprints.py`
  - `models/intents.py`

- `theseus/`  
  Exploration engine and pipelines:
  - `core/` – state tracker, fingerprint engine, exploration, exporter.
  - `drivers/` – web/desktop/mobile driver helpers.
  - `pipelines/` – simple and batch scan pipelines, sandbox tools.

- `atlas/`  
  UI graph schema, storage, and HTTP API:
  - `schema/` – context, state, transition, ontology.
  - `storage/` – in-memory graph store, signing.
  - `api/` – HTTP server, auth, ingest, query, health endpoints.

- `consumers/`  
  SDK and example clients for Atlas:
  - `sdk/` – Python client and typed views.
  - `examples/` – CLI and notebook examples.

- `config/`  
  Example configuration files:
  - `theseus.example.yml` – example scan configuration for Theseus.
  - `atlas.example.yml` – example server configuration for Atlas.
  - `logging.example.yml` – example Python logging configuration.

- `scripts/`  
  Utility scripts for running and developing:
  - `run_theseus.sh` – helper to run a Theseus scan with a config.
  - `run_atlas.sh` – helper to start the Atlas HTTP server.
  - `dev_env_setup.sh` – optional development environment bootstrap.
  - `data_export.py` – example data export utility.

- `docker/`  
  Docker files for local containerized runs:
  - `theseus.Dockerfile`
  - `atlas.Dockerfile`
  - `docker-compose.yml` – run Atlas and (optionally) Theseus together.

- `docs/` (optional, if present)  
  Additional documentation:
  - `index.md` – Ariane overview and the “UI as data” background.
  - `architecture/` – Theseus design, drivers, state fingerprinting, exploration logic.
  - `atlas/` – Atlas graph model and schema.
  - `usage/` – examples of how external systems (agents, tools, operator consoles) consume Atlas data.
  - `governance/` – licensing, privacy, and data integrity considerations.

- `.github/` (optional)  
  Issue templates, CI configuration, or automation for this repository.

---

## Status and scope

- This repository focuses on:
  - A reference implementation of the **UI graph model** (states, transitions, contexts).
  - A small, dependency-light **exploration engine** (Theseus).
  - A minimal, in-memory **graph store and HTTP API** (Atlas).
  - A simple **SDK and examples** for consuming the graph.

- It does **not** include:
  - A production-grade database backend.
  - A full automation framework for every platform.
  - A user-facing overlay or in-app guidance UI (these are considered separate consumers).

External tools, agents, or clients are expected to be built on top of the Atlas API and SDKs, using Ariane as the semantic map of software interfaces.
