if .status != "error" then
  "invalid: status must be error"
elif .error_type != "circular_dependency" then
  "invalid: error_type must be circular_dependency"
elif (has("cycle") | not) then
  "invalid: must have cycle"
elif (.cycle | type) != "array" then
  "invalid: cycle must be array"
elif (.cycle | length) < 3 then
  "invalid: cycle must have at least 3 entries"
elif (.cycle | first) != (.cycle | last) then
  "invalid: cycle must start and end with same module"
else
  "valid"
end
