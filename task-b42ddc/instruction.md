You are a network security engineer auditing the RPKI-based BGP route security infrastructure for AS 100. The organization has deployed RPKI with ROA-based Route Origin Validation and ASPA-based AS_PATH verification, but the RPKI repository integrity has been questioned after a security incident involving a compromised certificate authority.

The environment at `/app/` contains:

- `keys/` — Public keys (PEM) for four signing entities that issued RPKI objects
- `entity_registry.json` — Metadata about each signing entity and their status
- `revocation_list.json` — List of revoked signing entities with revocation details
- `rpki_objects/` — Individual ROA and ASPA data objects (JSON), each signed by a signing entity
- `signatures/` — Corresponding detached signatures for each RPKI object
- `roa_manifest.json` — Registry of ROA objects with references to their data files, signature files, and signing entities
- `aspa_manifest.json` — Registry of ASPA objects with references to their data files, signature files, and signing entities
- `rib.json` — BGP routing table with 60 routes (prefix, origin AS, AS_PATH, neighbor relationship)
- `topology.json` — AS business relationship graph (customer-provider and peer links)
- `attack_scenarios.json` — Eight attack scenarios to evaluate against the filtering policy
- `requirements.md` — Operator policy requirements specifying the composite filtering rules, risk scoring formula, ROV classification rules, and ASPA verification dispatch

Produce the following files at `/app/`:

- `trusted_objects.json` — Array of `{"id": "<ROA/ASPA ID>", "trusted": true|false, "reason": "valid"|"signing_entity_revoked"|"invalid_signature"}` for every ROA and ASPA object. Determine trust by verifying each object's detached signature against its signing entity's public key, and checking the revocation list.
- `rov_results.json` — Array of `{"route_id": "...", "rov_status": "Valid"|"Invalid"|"NotFound", "unsafe_maxlength": true|false}` for each route. A ROA is "unsafe" when its `max_length` exceeds the ROA prefix length by 4 or more bits.
- `aspa_results.json` — Array of `{"route_id": "...", "aspa_status": "Valid"|"Invalid"|"Unknown"}` for each route. Use only trusted ASPA objects. Follow the standard ASPA upstream/downstream verification algorithms as specified in `requirements.md`.
- `route_verdicts.json` — Array of `{"route_id": "...", "rov_status": "...", "aspa_status": "...", "unsafe_maxlength": true|false, "risk_score": <int>, "verdict": "ACCEPT"|"REJECT"|"REVIEW"}` combining ROV and ASPA results per the policy rules in `requirements.md`.
- `route_security.db` — SQLite database with tables `trusted_objects` (columns: `id TEXT`, `type TEXT`, `trusted INTEGER`, `reason TEXT`) and `route_verdicts` (columns: `route_id TEXT`, `prefix TEXT`, `origin_as INTEGER`, `relationship TEXT`, `rov_status TEXT`, `aspa_status TEXT`, `unsafe_maxlength INTEGER`, `risk_score INTEGER`, `verdict TEXT`).
- `policy_evaluation.json` — Array of `{"scenario_id": "...", "name": "...", "detected": true|false, "mitigated": true|false, "affected_route_verdicts": {"<route_id>": "<verdict>", ...}}` for each attack scenario. An attack is "detected" if any affected route is REJECT or REVIEW. An attack is "mitigated" if all affected routes are REJECT.