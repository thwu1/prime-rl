A retail company's transaction history is at `/app/data/transactions.csv` (columns: `transaction_id`, `customer_id`, `date`, `amount`). Planning parameters are in `/app/data/config.json`.

Examine the data, build a probabilistic model to predict per-customer lifetime value over the configured planning horizon, and write all results to `/app/results/`:

- `frequency_params.json` — `{"r": ..., "alpha": ..., "a": ..., "b": ...}` (all positive)
- `monetary_params.json` — `{"p": ..., "q": ..., "v": ...}` (all positive, `q` must exceed 1)
- `predictions.csv` — one row per customer with columns: `customer_id`, `p_alive`, `cond_expected_purchases`, `predicted_monetary_value`, `clv`
- `summary.json` — `{"total_clv": ..., "top_10_customer_ids": [...], "mean_p_alive": ..., "total_expected_purchases": ...}`

Customers with zero repeat purchases must have `predicted_monetary_value` and `clv` equal to 0.