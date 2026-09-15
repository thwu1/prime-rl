-- Strategy B: Lightweight indexes on high-cardinality filter columns
CREATE INDEX idx_b1 ON trades(side);
CREATE INDEX idx_b2 ON compliance_flags(flag_type);
