# Filter state update events
# Usage: jq -f states.jq server.ndjson
select(.event == "state_update") |
{trace, step, agent, x, y, energy, deactivated, deactivated_steps, comment}
