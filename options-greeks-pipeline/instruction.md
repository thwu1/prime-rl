`/app/data/` contains futures options market data:

- `quotes.bin` — Binary quote messages (see `format_spec.md`)
- `reference.db` — SQLite with instrument definitions and exchanges
- `config.toml` — Market parameters, reporting conventions, thresholds, output path
- `format_spec.md` — Binary format spec

Process this data and write results to the SQLite path in `config.toml` with these tables:

| Table | Columns |
|---|---|
| `nbbo` | `instrument_id`, `symbol`, `nbbo_bid`, `nbbo_ask`, `nbbo_mid` |
| `implied_volatility` | `instrument_id`, `symbol`, `strike`, `option_type`, `implied_vol` |
| `greeks` | `instrument_id`, `symbol`, `delta`, `gamma`, `theta`, `vega`, `rho` |
| `parity_violations` | `strike`, `call_mid`, `put_mid`, `theoretical_diff`, `actual_diff`, `violation_amount` |

Order by `instrument_id` (or `strike` for `parity_violations`).