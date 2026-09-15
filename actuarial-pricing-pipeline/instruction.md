An auto insurance portfolio is at `/app/data/policies.csv` (10,000 policies) with a partial data dictionary at `/app/data/README.md`. Five risk profiles that need pricing are at `/app/data/profiles.csv`.

Produce actuarially sound pure premium estimates (expected loss cost per policy) for each risk profile. The dataset has several statistical and data integrity problems that, if unaddressed, will produce materially incorrect pricing. Identifying and handling these problems is part of the task.

Save all deliverables to `/app/results/`:

**`diagnostics.json`** — Keys: `excluded_variables` (list of variable names excluded from your final models), `variable_concerns` (dict mapping each problematic variable name to a string describing the issue).

**`predictions.csv`** — Columns: `profile_id`, `predicted_frequency`, `predicted_severity`, `pure_premium`.

**`portfolio_summary.json`** — Keys: `mean_frequency` (float, predicted claims per policy at unit exposure), `mean_severity` (float, predicted mean claim cost), `mean_pure_premium` (float), `observed_loss_ratio` (float, sum of actual total losses across the portfolio divided by sum of model-predicted total losses).

Predictions will be validated against independently fitted reference models.