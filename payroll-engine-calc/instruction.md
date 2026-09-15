Build `/app/payroll_engine.py`, `/app/Makefile`, and `/app/payroll_validator.jq` to process payroll scenarios from `/app/payroll_input.json` according to the rules in `/app/reference/payroll_rules.md`.

Run: `make -C /app all`

**Makefile targets** (`/app/Makefile`):
- `run`: produces `/app/payroll_output.json` by executing the engine
- `validate`: runs `jq -ef payroll_validator.jq payroll_output.json` — must exit 0
- `report`: produces `/app/payroll_report.csv` from `payroll_output.json`
- `all`: runs the above targets in sequence

**Validator** (`/app/payroll_validator.jq`): a jq program that verifies all expected scenario IDs are present, each result contains required fields for its type, and net decomposition invariants hold within $0.02 tolerance. Outputs `{"valid": true, "scenarios_checked": N}` on success; causes non-zero exit on failure.

**Report** (`/app/payroll_report.csv`): CSV with header `scenario_id,type,gross,net`. One data row per scenario sorted alphabetically by `scenario_id`. `gross` maps to the primary gross field for each type (`gross_pay` for regular/regular_with_garnishment, `bonus_gross` for bonus_aggregate, `computed_gross` for gross_up, `total_retro_gross` for retro_pay). `net` maps to the final net field (`net_pay`, `net_pay_after_garnishment`, `net_bonus`, `actual_net`, `net_retro` respectively). Monetary values formatted to exactly 2 decimal places.

**Output JSON** — `/app/payroll_output.json`: `{"results": [...]}` with `id` and type-specific fields:

`regular`: `gross_pay`, `imputed_income`, `pretax_401k`, `pretax_health`, `fit_taxable_wages`, `fit_withholding`, `ss_taxable_wages`, `ss_tax`, `medicare_taxable_wages`, `medicare_tax`, `additional_medicare_tax`, `state_taxable_wages`, `state_tax`, `net_pay`

`bonus_aggregate`: `regular_gross`, `bonus_gross`, `fit_regular_only`, `fit_combined`, `fit_on_bonus`, `ss_on_bonus`, `medicare_on_bonus`, `additional_medicare_on_bonus`, `state_on_bonus`, `total_bonus_taxes`, `net_bonus`

`gross_up`: `desired_net`, `computed_gross`, `fit`, `ss_tax`, `medicare_tax`, `additional_medicare_tax`, `state_tax`, `total_taxes`, `actual_net`

`retro_pay`: `weeks` (array of `{week, regular_diff, ot_diff, total_diff}`), `total_retro_gross`, `fit`, `ss_tax`, `medicare_tax`, `additional_medicare_tax`, `state_tax`, `total_taxes`, `net_retro`

`regular_with_garnishment`: all `regular` fields plus `disposable_earnings`, `ccpa_limit_pct`, `max_garnishment`, `actual_garnishment`, `net_pay_after_garnishment`

All monetary values rounded to nearest cent, within $0.01 of expected.
