.PHONY: help simulate diagnose errors timeline cascade components test

help:
	@echo "Available diagnostic targets:"
	@echo "  simulate   - Run the config rollout simulation"
	@echo "  diagnose   - Show incident overview and event statistics"
	@echo "  errors     - Show all ERROR-level events"
	@echo "  timeline   - Show WARNING and ERROR events chronologically"
	@echo "  cascade    - Show events related to health failures and config loss"
	@echo "  components - List pipeline modules and sizes"
	@echo "  test       - Run the test suite"

simulate:
	python3 /app/run_simulation.py

diagnose:
	@echo "=== Incident Overview ==="
	@jq '{incident_id, severity, affected_sites, duration_minutes, triggered_by}' /app/data/incident_events.json
	@echo ""
	@echo "=== Event Count by Level ==="
	@jq '[.events[] | .level] | group_by(.) | map({level: .[0], count: length})' /app/data/incident_events.json
	@echo ""
	@echo "=== Events by Component ==="
	@jq '[.events[] | .component] | group_by(.) | map({component: .[0], count: length})' /app/data/incident_events.json

errors:
	@jq -r '.events[] | select(.level == "ERROR") | "\(.timestamp) [\(.component)] \(.message)"' /app/data/incident_events.json

timeline:
	@jq -r '.events[] | select(.level == "ERROR" or .level == "WARNING") | "\(.timestamp) \(.level) [\(.component)] \(.message)"' /app/data/incident_events.json

cascade:
	@echo "=== Health Impact Timeline ==="
	@jq -r '.events[] | select(.message | test("unhealthy|UNHEALTHY|health|HEALTH|MISSING|cleanup|Cleanup")) | "\(.seq). [\(.component)] \(.level): \(.message)"' /app/data/incident_events.json
	@echo ""
	@echo "=== Batch Failure Rates ==="
	@jq '.events[] | select(.details.batch_failures != null) | {seq, component, batch_failures: .details.batch_failures, batch_size: .details.batch_size}' /app/data/incident_events.json

components:
	@echo "=== Pipeline Components ==="
	@ls -la /app/config_pipeline/*.py
	@echo ""
	@echo "=== Module Sizes (lines) ==="
	@wc -l /app/config_pipeline/*.py

test:
	cd /app && python3 -m pytest /tests/test_state.py -v --tb=short
