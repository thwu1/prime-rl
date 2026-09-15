# Extract deadline boundary trace events — shows submit results at/around deadline
# Usage: jq -f deadline.jq server.ndjson
select(.trace == "deadline") |
if .event == "action_result" then {step, agent, action, result, comment}
elif .event == "score_update" then {step, team, score}
else empty end
