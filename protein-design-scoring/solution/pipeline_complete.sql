-- Protein design triage: SQLite scoring and ranking pipeline

CREATE TABLE IF NOT EXISTS metrics (
    design TEXT PRIMARY KEY,
    rmsd REAL,
    lddt REAL,
    tm_score REAL,
    gdt_ts REAL,
    interface_contacts INTEGER,
    hotspot_coverage REAL,
    interface_pae REAL,
    mean_plddt REAL
);

.mode csv
.import /app/metrics.csv metrics

-- Remove the header row that was imported as data
DELETE FROM metrics WHERE design = 'design';

-- Create ranked view with composite scores and quality filters
CREATE VIEW IF NOT EXISTS ranked_designs AS
SELECT
    design,
    rmsd,
    lddt,
    tm_score,
    gdt_ts,
    interface_contacts,
    hotspot_coverage,
    interface_pae,
    mean_plddt,
    (
        -0.15 * rmsd
        + 0.20 * lddt
        + 0.15 * tm_score
        + 0.15 * gdt_ts
        + 0.10 * hotspot_coverage
        + 0.10 * (mean_plddt / 100.0)
        + (-0.10) * (interface_pae / 31.75)
        + 0.05 * (CAST(interface_contacts AS REAL) / 40.0)
    ) AS composite_score
FROM metrics
WHERE rmsd < 20.0 AND mean_plddt > 50.0
ORDER BY composite_score DESC;
