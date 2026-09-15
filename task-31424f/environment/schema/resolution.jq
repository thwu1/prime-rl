if .status == "ok" then
  if (.modules | type) == "array" and (.modules | length) > 0 and (.modules | all(has("name") and has("version"))) then
    "valid"
  else
    "invalid: modules must be non-empty array with name and version fields"
  end
elif .status == "error" then
  if has("error_type") and has("message") then
    "valid"
  else
    "invalid: error must have error_type and message"
  end
else
  "invalid: status must be ok or error"
end
