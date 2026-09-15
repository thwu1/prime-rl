A SQLite database at `/app/data/market.db` stores synthetic monthly returns for 10 industry portfolios (table `monthly_returns`, long format with columns `period`, `industry`, `return_value`) and per-industry Amihud illiquidity measures (table `industry_info`). Backtest parameters reside in `/app/config.toml`. Explore the database schema and config to understand the full data layout.

Produce out-of-sample rolling-window backtest results comparing four allocation strategies under illiquidity-weighted turnover costs.

## Strategies

$\hat{\Sigma}$, $\hat{\mu}$ = unbiased sample covariance (ddof=1) and mean from the estimation window. $B = \text{diag}(\text{illiq}_1,\ldots,\text{illiq}_N)$. $\omega_{t^+}$ = weights after return-induced drift from the prior period. All strategies initialize at equal weights.

| Strategy | Definition |
|---|---|
| `naive` | Equal-weight: $\omega_i = 1/N$ |
| `mvp` | Minimum variance: $\omega = \hat{\Sigma}^{-1}\iota / (\iota'\hat{\Sigma}^{-1}\iota)$ |
| `mv_tc_iso` | $\arg\max_\omega \; \omega'\hat{\mu} - \frac{\beta}{2}\|\omega-\omega_{t^+}\|^2 - \frac{\gamma}{2}\omega'\hat{\Sigma}\omega$ s.t. $\iota'\omega=1$ |
| `mv_tc_illiq` | Same but with anisotropic cost: replace $\|\cdot\|^2$ with $(\omega-\omega_{t^+})'B(\omega-\omega_{t^+})$ |

Net period returns subtract illiquidity-weighted absolute turnover scaled by $\beta_{\text{eval}} / \text{tc\_scale}$. Annualized Sharpe: mean/std (ddof=1) $\times \sqrt{12}$.

## Required outputs (`/app/results/`)

| File | Content |
|---|---|
| `performance.json` | `{strategy: {sharpe_ratio, mean_return_ann_pct, volatility_ann_pct, avg_turnover}}` using `beta_default` for TC construction |
| `optimal_beta.json` | `{optimal_beta: <int>, sharpe_at_optimal: <float>}` — grid-search for best `mv_tc_illiq` construction $\beta$; evaluation cost fixed at `beta_default` |
| `strategy_ranking.json` | Strategy names sorted by Sharpe descending |
| `weights_period_250.json` | `{strategy: {industry_name: weight, ...}}` at out-of-sample period 250 (0-indexed) |
| `weight_history.parquet` | Full weight timeseries: columns `period` (int), `strategy` (str), plus one float column per industry name |