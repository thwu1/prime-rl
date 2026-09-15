
-- Index 1: Q1 Dashboard Pagination
-- Partial covering index eliminates both Sort and post-scan filtering.
-- Key insight: created_at DESC must come BEFORE the IN-list columns (status, event_type)
-- in the index key to preserve global ORDER BY without a Sort node.
-- The partial WHERE clause matches Q1's predicates exactly, so the planner
-- pre-filters at planning time — no runtime Filter needed.
-- INCLUDE covers all Q1 SELECT columns for Index Only Scan.
CREATE INDEX idx_q1_dashboard ON app.events
    (tenant_id, created_at DESC)
    INCLUDE (id, event_type, severity, status, source_system)
    WHERE status IN ('OPEN', 'ACKNOWLEDGED', 'IN_PROGRESS')
      AND event_type IN ('ALERT', 'INCIDENT', 'CHANGE');

-- Index 2: Q2 Time-Range Report + Q4 Critical Triage (shared)
-- tenant_id equality, then created_at ASC provides ordered scans for both queries.
-- INCLUDE columns make this a covering index for Q2, enabling Index Only Scan
-- which avoids heap access entirely — the planner strongly prefers this over
-- bitmap scan + sort, eliminating the Sort node for Q2.
-- Q2: range on created_at is an Index Cond, severity checked from INCLUDE (Filter).
--     Index Only Scan provides created_at ASC ordering without Sort.
-- Q4: regular Index Scan on same key ordering with LIMIT 20 stops early.
--     severity checked from INCLUDE, status/assigned_to/description from heap.
--     With ~9% match rate, scans ~220 rows to find 20 matches.
CREATE INDEX idx_q2q4_tenant_time ON app.events
    (tenant_id, created_at ASC)
    INCLUDE (id, event_type, severity, resolved_at);

-- Index 3: Q3 Resolution Metrics
-- tenant_id + status as equality conditions, resolved_at as range condition.
-- All three predicates become Index Conds (not Filters).
-- INCLUDE covers source_system and created_at needed for the aggregation query
-- to achieve Index Only Scan.
CREATE INDEX idx_q3_resolution ON app.events
    (tenant_id, status, resolved_at ASC)
    INCLUDE (source_system, created_at);

-- Index 4: Retention Deletes
-- Standalone created_at index for cross-tenant aged-out event cleanup.
-- The retention function scans by created_at order for efficient batched deletes.
CREATE INDEX idx_retention_created ON app.events
    (created_at ASC);
