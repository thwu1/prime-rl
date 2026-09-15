Three Terraform plan JSON scenarios at `/app/scenarios/{vpc_network,dns_loadbalancer,iam_permissions}/` each contain `plan.json` and `policy.rego`. OPA is installed at `/usr/local/bin/opa`.

Build `/app/mutester/main.py` accepting `--plan`, `--policy`, and `--output` arguments. It must implement mutation testing at three levels against Terraform plans validated by OPA Rego policies.

**First-order mutations**: Apply five operators (`field_removal`, `value_alteration`, `type_change`, `reference_break`, `resource_removal`) to the plan JSON and evaluate each mutant against the policy. The baseline (unmodified) plan must pass before mutating. A mutant is "killed" when the policy rejects it.

**Section-isolation analysis**: Terraform plan JSONs encode resources across three parallel sections: `configuration.root_module.resources[].expressions`, `planned_values.root_module.resources[].values`, and `resource_changes[].change.after`. For `field_removal` and `value_alteration` mutants, run each mutation in isolation per section (three additional runs per mutant), leaving other sections unchanged. Derive which sections each policy actually queries per field, and identify cross-section gaps where a field is validated in some sections but not others. For `type_change`, `reference_break`, and `resource_removal`, section-isolated results are `null`.

**Higher-order mutations**: For surviving first-order mutants on the same resource, test combined pairs. Report synergistic kills: pairs killed together when neither individual mutant was.

Each scenario must produce at least 15 first-order mutants with mutation score between 0.2 and 0.95. All `type_change` and `resource_removal` mutants must be killed. At least one cross-section gap must be found per scenario.

Write JSON to `--output` with this structure:

```json
{
  "total_mutants": int, "killed": int, "survived": int, "mutation_score": float,
  "operator_summary": {"<op>": {"total": int, "killed": int, "survived": int}},
  "mutants": [{
    "id": "mutant_NNNN", "operator": "<op>", "target_resource": "<addr>",
    "killed": bool,
    "section_results": {
      "all_sections": bool,
      "configuration_only": "bool|null",
      "planned_values_only": "bool|null",
      "resource_changes_only": "bool|null"
    }
  }],
  "coverage_analysis": {
    "<addr>": {"covered_fields": [...], "uncovered_fields": [...]}
  },
  "section_analysis": {
    "<addr>": {"<field>": {"detected_in_sections": [...], "undetected_in_sections": [...]}}
  },
  "cross_section_gaps": [
    {"resource": "<addr>", "field": "<field>", "validated_in": [...], "missing_in": [...]}
  ],
  "higher_order_results": {
    "pairs_tested": int, "synergistic_kills": int,
    "pairs": [{"mutant_a": "<id>", "mutant_b": "<id>", "combined_killed": bool}]
  }
}
```

`section_results.all_sections` must equal `killed`. Operator summaries must be consistent with individual mutant records. Cross-section gaps require non-empty `validated_in` and `missing_in`.