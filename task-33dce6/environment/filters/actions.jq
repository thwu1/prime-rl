# Filter action result events, optionally by trace
# Usage: jq -f actions.jq server.ndjson
#        jq --arg trace rotation -f actions.jq server.ndjson
select(.event == "action_result") |
if $ENV.TRACE then select(.trace == $ENV.TRACE) else . end |
{trace, step, agent, action, params, result, comment}
