.PHONY: help test diff-all diff-trace query-actions query-states query logs-filter schema

help:
	@echo "MASSim Engine Debug Toolkit"
	@echo ""
	@echo "  make test                  Run pytest suite"
	@echo "  make diff-all              Diff all traces against current engine"
	@echo "  make diff-trace T=<name>   Diff a single trace (rotation|deadline|connect|energy|wrapping|workflow|norms)"
	@echo "  make query-actions T=<name> Query expected action results for a trace"
	@echo "  make query-states T=<name>  Query expected agent states for a trace"
	@echo "  make query SQL=\"<sql>\"      Run arbitrary SQL on reference.db"
	@echo "  make logs-filter F=<name>   Run jq filter from /app/filters/<name>.jq"
	@echo "  make schema                Show reference.db schema"

test:
	cd /app && python3 -m pytest /tests/test_state.py -v 2>&1

diff-all:
	@for t in rotation deadline connect energy wrapping workflow norms; do \
		python3 /app/tools/trace_diff.py $$t 2>&1; \
	done

diff-trace:
	python3 /app/tools/trace_diff.py $(T)

query-actions:
	sqlite3 -header -column /app/reference.db \
		"SELECT step, agent, action_type, params, expected_result, comment FROM action_results WHERE trace='$(T)' ORDER BY step, agent"

query-states:
	sqlite3 -header -column /app/reference.db \
		"SELECT step, agent, x, y, energy, deactivated, deactivated_steps, comment FROM agent_states WHERE trace='$(T)' ORDER BY step, agent"

query:
	sqlite3 -header -column /app/reference.db "$(SQL)"

logs-filter:
	jq -f /app/filters/$(F).jq /app/logs/server.ndjson

schema:
	sqlite3 /app/reference.db ".schema"
