A startup's user acquisition data is in `/app/data/acquisition.db` (SQLite). A brief from the marketing team is at `/app/README.txt`.

The company's conversion rate dashboard reports declining performance across all channels over the past year, contradicting observed revenue growth. Investigate the data, identify the methodological flaw in the current measurement approach, and produce corrected channel performance metrics that marketing can trust for budget decisions.

Write results to `/app/results.json` with this structure:

- `methodology_flaw` (string): one-sentence explanation of why the dashboard produces misleading metrics
- `channels` (object keyed by channel name), each containing:
  - `naive_rate` (float): the dashboard's reported conversion rate
  - `true_rate` (float): corrected long-term conversion rate
  - `median_days_to_convert` (float): median time from signup to conversion in days
  - `cost_per_true_conversion` (float or null): dollars per conversion for paid channels, null for free channels
- `ranking` (list of strings): channels ordered by cost-effectiveness (ascending cost per conversion; free channels first)
- `budget_allocation` (object): paid channels only, budget fractions summing to approximately 1.0