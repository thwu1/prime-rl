The CDN proxy system at `/app/` has been crashing intermittently for hours, returning HTTP 5xx errors globally. A database permissions migration was recently applied to the distributed database cluster. Engineering suspects a connection between the migration and the crashes, but the intermittent failure pattern and concurrent DDoS alerts have complicated the investigation so far.

A management CLI is available at `/app/cfctl` (run `cfctl --help` for usage). Database shards are at `/app/db/shards/`, logs at `/app/logs/`, system configuration at `/app/config/settings.json`, and configuration change history at `/app/config/history/`. The feature generator is at `/app/generator/generate.py` and the proxy server at `/app/proxy/server.py`.

Investigate the root cause of the outage and fix all bugs contributing to the cascading failure. After your fixes, the system must satisfy these requirements:

1. **Stability**: All 5 database shards must produce identical, correct feature counts when used by the generator. The proxy must remain operational and serve traffic without crashing regardless of the configuration it receives, including malformed or unexpectedly large inputs. The generator must write configuration files in a way that is safe for concurrent readers.

2. **Validation**: Create a configuration validation module at `/app/config_safety/validator.py` that exports `validate_config(data: dict) -> tuple[bool, list[str]]` returning `(is_valid, error_messages)`. It must enforce the system's configuration invariants and integrate with `cfctl config validate`.

3. **Design document**: Write `/app/design_doc.md` analyzing the architectural weaknesses exposed by this incident — including error handling strategy trade-offs, deployment safety, and the validation invariants your module enforces with justification for each.

4. **Incident report**: Write `/app/incident_report.txt` documenting the full root cause chain from the database migration through the proxy crash, contributing factors, and prevention measures.