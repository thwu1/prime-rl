A robotics research lab's analysis pipeline at `/app/pipeline.py` processes experiment data from `/app/experiment.db` (SQLite) and real-world validation CSVs in `/app/real_validation/`. The pipeline runs without errors but produces statistically incorrect results across all five of its analysis modules.

The database stores binary success/failure rollout outcomes from three vision-language-action models evaluated across manipulation tasks under controlled perturbation conditions (visual, semantic, behavioral, and combined). Real-world validation data covers a subset of simulated conditions.

The pipeline writes JSON results to `/app/results/`:

- **Success rates with confidence intervals** — aggregates rollout outcomes per model/perturbation and computes binomial proportion CIs
- **Sensitivity decomposition** — measures performance degradation from baseline per perturbation category
- **Sim-to-real correlation** — computes rank correlation between simulated and real-world success rates with bootstrap CIs
- **Interaction effects** — tests whether combined perturbations produce non-additive degradation via permutation tests
- **Category importance attribution** — applies cooperative game theory (Shapley values) to attribute degradation across perturbation categories

Each module contains at least one bug affecting its statistical methodology, parameterization, or aggregation logic. The database schema includes configuration specifying the intended analysis methods — explore it thoroughly. Diagnose and fix all bugs so the pipeline produces correct results.