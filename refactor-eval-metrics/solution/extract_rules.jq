[
  .runs[]? |
  . as $run |
  ($run.tool.driver.rules // []) as $driver_rules |
  ($run.tool.extensions // []) as $extensions |
  $run.results[]? |
  select((.suppressions // []) | length == 0) |
  select((.kind // "fail") == "fail") |
  select((.level // "warning") != "none") |
  . as $r |
  (
    if $r.ruleId then $r.ruleId
    elif ($r.ruleIndex != null) then
      if ($r.rule.toolComponent.index != null) then
        ($extensions[$r.rule.toolComponent.index].rules[$r.ruleIndex].id // empty)
      else
        ($driver_rules[$r.ruleIndex].id // empty)
      end
    else empty
    end
  )
] | unique | .[]
