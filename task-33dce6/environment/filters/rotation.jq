# Extract rotation trace events — shows expected block positions after CW/CCW transforms
# Usage: jq -f rotation.jq server.ndjson
select(.trace == "rotation") |
if .event == "action_result" then {step, event, agent, action, result, comment}
elif .event == "block_update" then {step, event, x, y, type}
else empty end
