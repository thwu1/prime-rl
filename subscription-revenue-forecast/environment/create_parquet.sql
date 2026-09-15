-- DuckDB script to create hedge valuations Parquet file
-- Quarterly mark-to-market P&L data for IFRS 9 hedge effectiveness testing

CREATE TABLE hedge_valuations (
    contract_id VARCHAR,
    test_quarter VARCHAR,
    hedge_instrument_pnl DOUBLE,
    hedged_item_pnl DOUBLE
);

INSERT INTO hedge_valuations VALUES ('HC-2024-AUD-01', '2024-Q1', 62700.0, -66000.0);
INSERT INTO hedge_valuations VALUES ('HC-2024-AUD-01', '2024-Q2', 79800.0, -84000.0);
INSERT INTO hedge_valuations VALUES ('HC-2024-AUD-01', '2024-Q3', 74100.0, -78000.0);
INSERT INTO hedge_valuations VALUES ('HC-2024-AUD-01', '2024-Q4', 68400.0, -72000.0);
INSERT INTO hedge_valuations VALUES ('HC-2025-AUD-01', '2025-Q1', 65049.6, -73920.0);
INSERT INTO hedge_valuations VALUES ('HC-2025-AUD-01', '2025-Q2', 82790.4, -94080.0);
INSERT INTO hedge_valuations VALUES ('HC-2025-AUD-01', '2025-Q3', 76876.8, -87360.0);
INSERT INTO hedge_valuations VALUES ('HC-2025-AUD-01', '2025-Q4', 70963.2, -80640.0);
INSERT INTO hedge_valuations VALUES ('HC-2026-AUD-01', '2026-Q1', 85932.0, -81840.0);
INSERT INTO hedge_valuations VALUES ('HC-2026-AUD-01', '2026-Q2', 109368.0, -104160.0);
INSERT INTO hedge_valuations VALUES ('HC-2026-AUD-01', '2026-Q3', 101556.0, -96720.0);
INSERT INTO hedge_valuations VALUES ('HC-2026-AUD-01', '2026-Q4', 93744.0, -89280.0);
INSERT INTO hedge_valuations VALUES ('HC-2027-AUD-01', '2027-Q1', 118483.2, -89760.0);
INSERT INTO hedge_valuations VALUES ('HC-2027-AUD-01', '2027-Q2', 150796.8, -114240.0);
INSERT INTO hedge_valuations VALUES ('HC-2027-AUD-01', '2027-Q3', 140025.6, -106080.0);
INSERT INTO hedge_valuations VALUES ('HC-2027-AUD-01', '2027-Q4', 129254.4, -97920.0);
INSERT INTO hedge_valuations VALUES ('HC-2028-AUD-01', '2028-Q1', 88888.8, -97680.0);
INSERT INTO hedge_valuations VALUES ('HC-2028-AUD-01', '2028-Q2', 113131.2, -124320.0);
INSERT INTO hedge_valuations VALUES ('HC-2028-AUD-01', '2028-Q3', 105050.4, -115440.0);
INSERT INTO hedge_valuations VALUES ('HC-2028-AUD-01', '2028-Q4', 96969.6, -106560.0);
INSERT INTO hedge_valuations VALUES ('HC-2024-GBP-01', '2024-Q1', 113097.6, -110880.0);
INSERT INTO hedge_valuations VALUES ('HC-2024-GBP-01', '2024-Q2', 143942.4, -141120.0);
INSERT INTO hedge_valuations VALUES ('HC-2024-GBP-01', '2024-Q3', 133660.8, -131040.0);
INSERT INTO hedge_valuations VALUES ('HC-2024-GBP-01', '2024-Q4', 123379.2, -120960.0);
INSERT INTO hedge_valuations VALUES ('HC-2025-GBP-01', '2025-Q1', 110484.0, -118800.0);
INSERT INTO hedge_valuations VALUES ('HC-2025-GBP-01', '2025-Q2', 140616.0, -151200.0);
INSERT INTO hedge_valuations VALUES ('HC-2025-GBP-01', '2025-Q3', 130572.0, -140400.0);
INSERT INTO hedge_valuations VALUES ('HC-2025-GBP-01', '2025-Q4', 120528.0, -129600.0);
INSERT INTO hedge_valuations VALUES ('HC-2026-GBP-01', '2026-Q1', 108979.2, -126720.0);
INSERT INTO hedge_valuations VALUES ('HC-2026-GBP-01', '2026-Q2', 138700.8, -161280.0);
INSERT INTO hedge_valuations VALUES ('HC-2026-GBP-01', '2026-Q3', 128793.6, -149760.0);
INSERT INTO hedge_valuations VALUES ('HC-2026-GBP-01', '2026-Q4', 118886.4, -138240.0);
INSERT INTO hedge_valuations VALUES ('HC-2027-GBP-01', '2027-Q1', 158875.2, -134640.0);
INSERT INTO hedge_valuations VALUES ('HC-2027-GBP-01', '2027-Q2', 202204.8, -171360.0);
INSERT INTO hedge_valuations VALUES ('HC-2027-GBP-01', '2027-Q3', 187761.6, -159120.0);
INSERT INTO hedge_valuations VALUES ('HC-2027-GBP-01', '2027-Q4', 173318.4, -146880.0);
INSERT INTO hedge_valuations VALUES ('HC-2028-GBP-01', '2028-Q1', 105494.4, -142560.0);
INSERT INTO hedge_valuations VALUES ('HC-2028-GBP-01', '2028-Q2', 134265.6, -181440.0);
INSERT INTO hedge_valuations VALUES ('HC-2028-GBP-01', '2028-Q3', 124675.2, -168480.0);
INSERT INTO hedge_valuations VALUES ('HC-2028-GBP-01', '2028-Q4', 115084.8, -155520.0);

COPY hedge_valuations TO '/app/data/hedge_valuations.parquet' (FORMAT PARQUET);
