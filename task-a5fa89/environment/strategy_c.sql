-- Strategy C: Supporting indexes on reference/lookup tables
CREATE INDEX idx_c1 ON instruments(ticker);
CREATE INDEX idx_c2 ON instruments(asset_class);
CREATE INDEX idx_c3 ON traders(desk);
CREATE INDEX idx_c4 ON traders(name);
