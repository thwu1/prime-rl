# Track energy changes across steps — useful for debugging recharge/deactivation lifecycle
# Usage: jq -f energy.jq server.ndjson
select(.event == "state_update" and .energy != null) |
{trace, step, agent, energy, deactivated, deactivated_steps}
