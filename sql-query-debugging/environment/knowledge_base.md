# Trading Analytics Knowledge Base

## Business Rules and Data Conventions

This document defines the authoritative business rules for computing trading desk
analytics metrics. All analytical queries MUST follow these rules exactly.

### Rule 1 -- Net Position

The **net position** for a trader-instrument pair is computed as:

    net_position = SUM(quantity x direction_sign)

where `direction_sign` is `+1` for BUY and `-1` for SELL. Only **settled** trades
(`status = 'settled'`) are included. Cancelled and pending trades are excluded.

### Rule 2 -- Profit and Loss (PnL)

    PnL = SUM(quantity x price x direction_sign) - SUM(commission)

where `direction_sign` is `-1` for BUY (cash outflow) and `+1` for SELL (cash inflow).
Only **settled** trades are included. If `commission` is NULL for a trade, treat it
as zero (do not allow NULL to propagate through aggregation).

### Rule 3 -- T+2 Settlement (Business Days)

Expected settlement date is the trade date plus **two business days**. Business days
exclude Saturday and Sunday (but do not exclude public holidays for this dataset).

Examples:
- Trade on Monday -> settles Wednesday (+2 calendar days)
- Trade on Tuesday -> settles Thursday (+2 calendar days)
- Trade on Wednesday -> settles Friday (+2 calendar days)
- Trade on Thursday -> settles Monday (+4 calendar days, skipping Sat/Sun)
- Trade on Friday -> settles Tuesday (+4 calendar days, skipping Sat/Sun)

A **settlement anomaly** is any settled trade where the actual `settlement_date`
differs from the expected T+2 business-day date.

### Rule 4 -- Volume-Weighted Average Price (VWAP)

    VWAP = SUM(close_price x volume) / SUM(volume)

Days where `volume = 0` MUST be excluded from both numerator and denominator.
These represent data gaps or non-trading sessions and including them would distort
the average.

### Rule 5 -- Trader Seniority

Seniority is determined by years of service as of 2024-03-31:
- **Junior**: less than 3 years
- **Mid**: 3 to 7 years (inclusive)
- **Senior**: more than 7 years

### Rule 6 -- Risk Utilization

    risk_utilization_pct = |net_position| / max_position x 100

where `net_position` is calculated per Rule 1, and `max_position` comes from the
**most recently effective** risk limit. The absolute value is required because short
positions (negative net) still consume risk capacity.

### Rule 7 -- Applicable Risk Limit Selection

When multiple risk limits exist for a (trader, asset_class) pair, use the one with
the most recent `effective_date` that satisfies:

    effective_date <= reference_date AND (expiry_date IS NULL OR expiry_date > reference_date)

where `reference_date` is 2024-03-31 (end of Q1). Expired limits MUST be excluded.

### Rule 8 -- Active Traders Only for Desk-Level Metrics

Desk-level statistics (PnL summaries, headcounts, averages) MUST include only
**active** traders (`is_active = 1`). Inactive traders' trades still exist in the
database for audit purposes but are excluded from desk reporting.

### Rule 9 -- Fiscal Quarter

Q1 2024 covers January 1, 2024 through March 31, 2024 inclusive. Date range filters
should use `trade_date >= '2024-01-01' AND trade_date <= '2024-03-31'` (or BETWEEN).

### Rule 10 -- NULL Commission Handling

When `commission` is NULL, treat it as zero for all calculations. Use COALESCE or
equivalent to prevent NULL propagation. This is critical for PnL calculations where
a single NULL commission could invalidate an entire aggregation if not handled.

### Rule 11 -- Mark-to-Market Valuation

When computing the current market value of a position, use the **latest valid
closing price** from `daily_prices`. A valid price entry is one where `volume > 0`
(consistent with Rule 4 -- zero-volume entries represent data gaps, not valid market
prices). If no valid price exists for an instrument, that position cannot be valued
and should be excluded from valuation reports.

    market_value = net_position x latest_valid_close_price

### Rule 12 -- Per-Trader Aggregation Before Cross-Trader Metrics

When computing averages or other aggregate metrics across a group of traders (e.g.,
average P&L per seniority band), first compute the metric at the individual trader
level, then aggregate across traders. Computing an average directly from trade-level
values produces statistically misleading results because traders with more trades
would be over-represented in the average.
