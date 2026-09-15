-- NMS Inventory Database for ISP backbone
-- Provides operational data for billing and risk assessment

CREATE TABLE link_pricing (
    link_key TEXT PRIMARY KEY,
    cost_per_gbps_month INTEGER NOT NULL
);

INSERT INTO link_pricing VALUES ('A-B', 1200);
INSERT INTO link_pricing VALUES ('A-C', 800);
INSERT INTO link_pricing VALUES ('B-D', 1500);
INSERT INTO link_pricing VALUES ('B-E', 1100);
INSERT INTO link_pricing VALUES ('C-D', 900);
INSERT INTO link_pricing VALUES ('C-E', 2000);
INSERT INTO link_pricing VALUES ('D-E', 1000);

CREATE TABLE srlg_risk_scores (
    srlg_id INTEGER PRIMARY KEY,
    risk_score REAL NOT NULL,
    description TEXT
);

INSERT INTO srlg_risk_scores VALUES (1, 0.85, 'Fiber ring segment North — shared conduit');
INSERT INTO srlg_risk_scores VALUES (2, 0.45, 'Fiber ring segment West — diverse duct');
INSERT INTO srlg_risk_scores VALUES (3, 0.65, 'Metro cross-connect — shared building entry');
INSERT INTO srlg_risk_scores VALUES (4, 0.30, 'Diverse path segment — separate ROW');
INSERT INTO srlg_risk_scores VALUES (5, 0.90, 'Submarine single point of failure');

CREATE TABLE customer_circuits (
    lsp_name TEXT PRIMARY KEY,
    customer TEXT NOT NULL,
    sla_tier TEXT NOT NULL
);

INSERT INTO customer_circuits VALUES ('lsp-gold', 'ACME Corp', 'platinum');
INSERT INTO customer_circuits VALUES ('lsp-silver', 'Beta Inc', 'gold');
INSERT INTO customer_circuits VALUES ('lsp-diverse-1', 'ACME Corp', 'gold');
INSERT INTO customer_circuits VALUES ('lsp-diverse-2', 'ACME Corp', 'silver');
INSERT INTO customer_circuits VALUES ('lsp-best-effort', 'Gamma LLC', 'bronze');
INSERT INTO customer_circuits VALUES ('lsp-premium', 'Delta Corp', 'platinum');
INSERT INTO customer_circuits VALUES ('lsp-constrained', 'Beta Inc', 'silver');
