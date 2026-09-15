
.PHONY: simulate trace summary lint-scenario

simulate:
	@python3 -m rail_sim.simulator $(SCENARIO)

trace:
	@python3 -m rail_sim.simulator $(SCENARIO) --trace-db $(DB)

summary:
	@total_steps=$$(sqlite3 $(DB) "SELECT MAX(step) FROM agent_traces"); \
	num_agents=$$(sqlite3 $(DB) "SELECT COUNT(DISTINCT agent_handle) FROM agent_traces"); \
	finals=$$(sqlite3 -json $(DB) "SELECT CAST(agent_handle AS TEXT) as handle, state FROM agent_traces WHERE step=(SELECT MAX(step) FROM agent_traces)"); \
	echo "$$finals" | jq --arg ts "$$total_steps" --arg na "$$num_agents" \
		'{total_steps: ($$ts|tonumber), agents: ($$na|tonumber), final_states: (map({(.handle): .state}) | add)}'

lint-scenario:
	@jq -e 'has("agents") and has("actions") and has("max_steps")' $(SCENARIO) > /dev/null
