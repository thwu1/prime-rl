-- Strategy A: Covering indexes for maximum query coverage
-- Includes all selected columns in each index to avoid table lookups
CREATE INDEX idx_a1 ON trades(trader_id, trade_date, id, instrument_id, side, quantity, price);
CREATE INDEX idx_a2 ON trades(instrument_id, price, id, trader_id, side, quantity, trade_date);
CREATE INDEX idx_a3 ON compliance_flags(severity, resolved, id, trade_id, flag_type);
CREATE INDEX idx_a4 ON trades(trade_date, id, trader_id, instrument_id, side, quantity, price);
