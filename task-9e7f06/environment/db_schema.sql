-- Required schema for /app/output/autotune.db
-- Create this database with the exact table structure, index, and views below.

-- Table: configurations
-- One row per valid kernel configuration with computed occupancy metrics.
CREATE TABLE configurations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    num_threads INTEGER NOT NULL,
    bm INTEGER NOT NULL,
    bn INTEGER NOT NULL,
    bk INTEGER NOT NULL,
    wm INTEGER NOT NULL,
    wn INTEGER NOT NULL,
    wniter INTEGER NOT NULL,
    tm INTEGER NOT NULL,
    tn INTEGER NOT NULL,
    wmiter INTEGER NOT NULL,
    regs_per_thread INTEGER NOT NULL,
    smem_data_bytes INTEGER NOT NULL,
    smem_allocated_bytes INTEGER NOT NULL,
    max_blocks_by_regs INTEGER NOT NULL,
    max_blocks_by_smem INTEGER NOT NULL,
    max_blocks_by_warps INTEGER NOT NULL,
    max_blocks_per_sm INTEGER NOT NULL,
    active_warps INTEGER NOT NULL,
    occupancy_pct REAL NOT NULL,
    UNIQUE(num_threads, bm, bn, bk, wm, wn, wniter, tm, tn)
);

-- Table: bottlenecks
-- Normalized table linking each configuration to its bottleneck resource(s).
-- A configuration may have multiple bottleneck resources when two or more
-- resource limits tie for the minimum max_blocks_per_sm value.
CREATE TABLE bottlenecks (
    config_id INTEGER NOT NULL REFERENCES configurations(id),
    resource TEXT NOT NULL CHECK(resource IN ('registers', 'smem', 'warps')),
    PRIMARY KEY (config_id, resource)
);

-- Required index for occupancy-based queries
CREATE INDEX idx_configs_occupancy ON configurations(occupancy_pct);

-- View: occupancy_histogram
-- Must return columns: occupancy_pct (REAL), config_count (INTEGER)
-- One row per distinct occupancy level, ordered by occupancy_pct ascending.

-- View: bottleneck_distribution
-- Must return columns: category (TEXT), config_count (INTEGER)
-- Categories: 'registers_only', 'smem_only', 'warps_only', 'multiple'
-- A config is classified as 'multiple' if it has more than one bottleneck resource.
-- Only include categories that have config_count > 0.
