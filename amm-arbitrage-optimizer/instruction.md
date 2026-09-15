A decentralized exchange consisting of multiple automated market maker (AMM) pools is defined in the SQLite database at `/app/market.db`. Pool configuration is spread across normalized tables with type-specific parameters stored separately — examine the schema to understand the data model and the distinct pool types present.

A swap-quote utility is installed at `/usr/local/bin/swap-quote` (run with `--help` for usage).

Analyze the complete pool topology to identify the single most profitable arbitrage opportunity across all possible trading paths. Determine the trade size that maximizes absolute profit, accounting for all fees and price impact. Pools are bidirectional.

Write results to `/app/results.json`:

```json
{
  "best_cycle_path": ["TOKEN_START", "TOKEN_2", ..., "TOKEN_START"],
  "best_cycle_pools": ["pool_id_1", "pool_id_2", ...],
  "optimal_input_amount": <float>,
  "expected_output_amount": <float>,
  "expected_profit": <float>
}
```

- `best_cycle_path`: ordered token sequence traversed (first element equals last)
- `best_cycle_pools`: pool used for each consecutive swap (length = len(path) - 1)
- `optimal_input_amount`: trade size in the starting token maximizing absolute profit
- `expected_output_amount`: amount received after completing the full path at optimal input
- `expected_profit`: `expected_output_amount - optimal_input_amount`