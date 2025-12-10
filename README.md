# Ariane

Ariane is a semantic infrastructure project that treats user interfaces as data.

It defines a universal graph model for software UIs and a set of tools to explore and store that graph so that external AI systems can read it as a reference when guiding users through software.

Core components:

- **Theseus** – a platform-agnostic crawler that explores applications and extracts UI states and transitions.
- **Atlas** – a formal ontology and graph schema that stores UI states, transitions, and semantic intents as an open, machine-readable graph.

This repository focuses on specifications and documentation for the architecture, data model, and roadmap of this UI graph.

Any UI overlay or in-app guidance client is considered an external consumer of this data and is out of scope for the initial project, but may be explored later as a separate implementation or subproject.

## Repository layout

- `README.md`  
  High-level description of the project and links into the documentation.

- `docs/`  
  Project documentation and design specs:
  - `index.md` – overview of Ariane and the procedural knowledge gap.
  - `architecture/` – Theseus design, drivers, state fingerprinting, and exploration logic.
  - `atlas/` – Atlas overview and the UI graph schema (States, Transitions, ontology).
  - `usage/` (optional) – examples of how external AI systems or tools can consume the Atlas data to guide users, including a possible future overlay-style client.
  - `roadmap/` – conceptual development phases and risk matrix (no calendar).
  - `governance/` – licensing, legal basis, privacy, and data integrity.

- `.github/` (optional)  
  Issue templates or CI configuration related to the project.
