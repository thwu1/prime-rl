# Filter for norm-related deactivation events
# Usage: jq -f norms.jq server.ndjson
select(.event == "state_update" and .deactivated == true) |
{trace, step, agent, energy, deactivated_steps, comment}
