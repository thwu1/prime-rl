if .status != "error" then
  "invalid: status must be error"
elif (has("conflicts") | not) then
  "invalid: must have conflicts"
elif (.conflicts | type) != "array" then
  "invalid: conflicts must be array"
elif (.conflicts | length) == 0 then
  "invalid: conflicts must not be empty"
elif (.conflicts | all(has("module") and has("unsatisfiable_constraints"))) | not then
  "invalid: each conflict needs module and unsatisfiable_constraints"
elif (.conflicts | all(.unsatisfiable_constraints | type == "array")) | not then
  "invalid: unsatisfiable_constraints must be arrays"
elif (.conflicts | all(.unsatisfiable_constraints | all(has("required_by") and has("constraint")))) | not then
  "invalid: each constraint needs required_by and constraint"
else
  "valid"
end
