Implement the core modules for a clinical case simulation engine inspired by the USMLE Step 3 Computer-based Case Simulations (CCS/Primum) format. The framework provides data models, a patient case definition (acute STEMI scenario), an order catalog with 35+ entries, a scoring rubric, and a CLI runner.

Three Python modules require implementation according to the API contracts specified in their docstrings:

- **`/app/order_matcher.py`** — Fuzzy text matching system that maps free-text clinical orders to canonical catalog entries. Must implement four matching strategies (exact, prefix, token-subset, Levenshtein edit-distance) with location-aware filtering. Pure Python implementation required (no external packages).

- **`/app/simulation.py`** — Discrete-event simulation engine that accepts clinical orders via the OrderMatcher, advances a simulated clock minute-by-minute, evaluates conditional timeline events using a recursive dictionary-based expression language (`has_order`, `not`, `and`, `or`, `location_is`, `flag_set`), delivers order results based on processing times, and tracks patient state across care locations.

- **`/app/scorer.py`** — Scoring algorithm that evaluates a completed simulation transcript against an expert-defined rubric. Must handle time-windowed credit with linear decay for late actions, DAG-aware prerequisite sequencing validation, risk-weighted penalties for contraindicated actions, and score aggregation with clamping to [0, max_score].

Supporting data files in `/data/`: `catalog.json` (order catalog with aliases and processing times), `case.json` (case definition with initial state and conditional event timeline), `rubric.json` (scoring rubric with 15 items). Reference Python modules in `/app/`: `models.py` (reference data model definitions), `runner.py` (CLI orchestrator that loads data from `/data/`).

All implementations must use only Python standard library — no external packages.