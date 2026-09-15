
def abs_val: if . < 0 then (- .) else . end;
def has_all(ks): . as $obj | [ks[] | . as $k | $obj | has($k)] | all;

. as $input |

# Check all scenario IDs present
($input.results | map(.id) | sort) as $ids |
if $ids != ["chen_regular","davis_garnishment","johnson_grossup","kim_medicare","martinez_bonus","patel_retro"] then
  "Expected 6 scenarios, got \($ids | tostring)" | error
else null end |

# Check required fields per type
[$input.results[] |
  if .type == "regular" then
    has_all(["gross_pay","imputed_income","pretax_401k","pretax_health","fit_withholding","ss_tax","medicare_tax","additional_medicare_tax","state_tax","net_pay"])
  elif .type == "regular_with_garnishment" then
    has_all(["gross_pay","net_pay","disposable_earnings","ccpa_limit_pct","max_garnishment","actual_garnishment","net_pay_after_garnishment"])
  elif .type == "bonus_aggregate" then
    has_all(["regular_gross","bonus_gross","fit_on_bonus","total_bonus_taxes","net_bonus"])
  elif .type == "gross_up" then
    has_all(["desired_net","computed_gross","fit","total_taxes","actual_net"])
  elif .type == "retro_pay" then
    has_all(["weeks","total_retro_gross","fit","total_taxes","net_retro"])
  else false end
] as $field_checks |
if ($field_checks | all | not) then
  "Missing required fields in one or more scenarios" | error
else null end |

# Check net decomposition invariants
[$input.results[] |
  if .type == "regular" then
    (.gross_pay - .pretax_401k - .pretax_health - .fit_withholding - .ss_tax - .medicare_tax - .additional_medicare_tax - .state_tax - .net_pay | abs_val) < 0.02
  elif .type == "regular_with_garnishment" then
    ((.gross_pay - .pretax_401k - .pretax_health - .fit_withholding - .ss_tax - .medicare_tax - .additional_medicare_tax - .state_tax - .net_pay | abs_val) < 0.02)
    and ((.net_pay - .actual_garnishment - .net_pay_after_garnishment | abs_val) < 0.02)
  elif .type == "bonus_aggregate" then
    (.bonus_gross - .total_bonus_taxes - .net_bonus | abs_val) < 0.02
  elif .type == "gross_up" then
    (.computed_gross - .total_taxes - .actual_net | abs_val) < 0.02
  elif .type == "retro_pay" then
    (.total_retro_gross - .total_taxes - .net_retro | abs_val) < 0.02
  else false end
] as $decomp_checks |
if ($decomp_checks | all | not) then
  "Net decomposition invariant failed for one or more scenarios" | error
else null end |

{"valid": true, "scenarios_checked": ($input.results | length)}
