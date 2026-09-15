# Excerpt from "CORE-Bench: Fostering the Credibility of Published Research Through a Computational Reproducibility Agent Benchmark"

## 3.2 Evaluation Methodology

Our evaluation framework quantifies agent success in reproducing computational results from published scientific capsules. Because many scientific codebases exhibit inherent stochasticity—from random initialization, Monte Carlo methods, or stochastic gradient descent—each capsule is executed *N* independent times to establish ground-truth baselines. Evaluation metrics are classified into two categories based on their key names: **vision questions**, identified by the presence of the substring `fig` anywhere in the key name (reflecting metrics derived from figure analysis), and **written questions** (all remaining metrics). This distinction captures whether the agent needed to interpret a visual output or extract a textual/numeric result from the capsule's execution.

### 3.2.1 Numeric Evaluation via Prediction Intervals

Numeric results require statistical handling to accommodate stochastic variability across runs. We employ **95% prediction intervals** computed from the ground-truth run distribution. The critical distinction from confidence intervals is that prediction intervals bound the range of a *new, future observation* rather than the population mean, and thus incorporate both estimation uncertainty and natural variability. Concretely, given *n* ground-truth runs with sample mean μ̂ and Bessel-corrected sample standard deviation *s*, the two-sided 95% prediction interval is:

    μ̂  ±  t₀.₉₇₅, ₙ₋₁  ·  s  ·  √(1 + 1/n)

where t₀.₉₇₅, ₙ₋₁ denotes the 97.5th percentile of the Student's t-distribution with *n* − 1 degrees of freedom. Note the use of the 97.5th (not 95th) percentile, which yields a *two-sided* 95% interval; the factor √(1 + 1/n) rather than √(1/n) is what distinguishes a prediction interval from a confidence interval for the mean. An agent-reported numeric value is judged **correct** if it falls within the closed interval [lower, upper]. In the degenerate case where all *N* runs produce identical values (s = 0), the prediction interval collapses to [μ̂, μ̂], and a reported value must match exactly.

### 3.2.2 String and List Evaluation

String comparisons use **case-insensitive** exact matching to accommodate superficial formatting differences between agent implementations (e.g., `"RandomForest"` vs `"randomforest"`). List-type results are compared via direct equality against the first ground-truth run's value.

### 3.2.3 Value Coercion

Agent-reported values undergo coercion before comparison: if a reported value is a string, leading and trailing whitespace is stripped; if the resulting string ends with a percent sign (`%`), the sign is removed; the string is then parsed as a float if possible. This handles common formatting variations such as `"45.2%"` being treated equivalently to `45.2`.

### 3.2.4 Aggregate Scoring

A capsule is considered fully reproduced (a **correct task**) when every metric in that capsule—both vision and written—is judged correct. We separately track task-level and question-level accuracy, disaggregated by vision and written categories. A **correct written task** is a capsule where all written questions are answered correctly and at least one written question exists; the definition for **correct vision task** is analogous. **Total written tasks** and **total vision tasks** count only capsules that contain at least one question of the respective type. Missing keys in an agent's report are treated as incorrect answers.
