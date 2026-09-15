Create an executable `/app/portfolio` that parses the ledger-cli journal at `/app/portfolio.journal` and supports four subcommands producing JSON to stdout.

**`portfolio lots`**
Flags: `--date YYYY/MM/DD` (optional cutoff, only process transactions up to this date), `--method fifo|lifo|hifo` (default: `fifo`).
Output: `{"lots": [{commodity, quantity, cost_per_unit, total_cost, acquisition_date}]}` sorted ascending by `(acquisition_date, commodity, cost_per_unit)`. Wash-sale-adjusted lots reflect their adjusted cost basis. Only `Assets:Brokerage` commodity postings create lots; virtual postings (parenthesized/bracketed accounts), dividends, and cash movements must be excluded.

**`portfolio realized-gains`**
Flags: `--date YYYY/MM/DD`, `--method fifo|lifo|hifo`.
Each transaction: `{date, commodity, quantity_sold, sale_price_per_unit, total_proceeds, total_cost_basis, realized_gain, wash_sale_disallowed, adjusted_gain, holding_period}`.
Summary fields: `total_realized_gain`, `total_wash_sale_disallowed`, `total_adjusted_gain`, `short_term_adjusted_gain`, `long_term_adjusted_gain`.

**`portfolio market-value`**
Flags: `--date YYYY/MM/DD` (required), `--method fifo|lifo|hifo`.
Output: `{date, holdings: [{commodity, total_quantity, market_price, market_value}], total_market_value, total_cost_basis, total_unrealized_gain}`. Holdings sorted by commodity. Cost basis reflects wash-sale adjustments. Market prices come from `P` directives in the journal (use the most recent price on or before the given date).

**`portfolio validate`**
Flags: `--date YYYY/MM/DD` (required).
Output: `{valid: bool, holdings: {commodity: qty}, ledger_holdings: {commodity: qty}}`. Cross-checks per-commodity share quantities against `ledger` CLI balance output for `Assets:Brokerage`.

**Lot methods:**
`fifo` — first-in, first-out. `lifo` — last-in, first-out. `hifo` — highest cost per unit consumed first.

**Wash sale rule (forward-looking):** When a sell produces a loss and shares of the same commodity are purchased within 30 calendar days after the sell date, the loss is partially or fully disallowed. `replacement_shares = min(total_bought_in_window, shares_sold)`. `wash_sale_disallowed = (replacement_shares / shares_sold) * |loss|`, rounded to 2 decimal places. `adjusted_gain = realized_gain + wash_sale_disallowed`. The disallowed amount is added to the replacement lot's total cost basis, distributed proportionally across all replacement lots, affecting all downstream outputs.

**Holding period:** `"short-term"` if the earliest consumed lot was acquired 365 days or fewer before the sale date; `"long-term"` otherwise.

**Journal features to handle:** automated transactions (`=`), virtual postings (parenthesized/bracketed accounts), cleared markers (`*`), tag metadata, lot annotations (`{$cost} [date]`), total-cost syntax (`@@ $total`), and commented-out entries. All monetary output values rounded to 2 decimal places. Exit 0 on success, non-zero on error.
