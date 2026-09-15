
-- ============================================================
-- Five critical queries for the event monitoring system.
-- Create at most 4 secondary indexes total to optimize all of them.
-- Test tenant: a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11
-- ============================================================

-- Q1: Dashboard Pagination
-- Latest 50 active events for a tenant, filtered by status and type.
SELECT id, event_type, severity, created_at, status, source_system
FROM app.events
WHERE tenant_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'
  AND status IN ('OPEN', 'ACKNOWLEDGED', 'IN_PROGRESS')
  AND event_type IN ('ALERT', 'INCIDENT', 'CHANGE')
ORDER BY created_at DESC
LIMIT 50;

-- Q2: Time-Range Severity Report
-- High-severity events in a date range, ordered chronologically.
SELECT id, event_type, severity, created_at, resolved_at
FROM app.events
WHERE tenant_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'
  AND created_at >= '2024-03-01'::timestamptz
  AND created_at < '2024-04-01'::timestamptz
  AND severity >= 4
ORDER BY created_at ASC;

-- Q3: Resolution Metrics by Source System
-- Aggregate resolution times for resolved events in a date range.
SELECT source_system,
       COUNT(*) as event_count,
       AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))) as avg_resolution_secs
FROM app.events
WHERE tenant_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'
  AND status = 'RESOLVED'
  AND resolved_at >= '2024-03-01'::timestamptz
  AND resolved_at < '2024-06-01'::timestamptz
GROUP BY source_system;

-- Q4: Critical Unresolved Events Triage
-- Oldest 20 high-severity unresolved events for triage queue.
SELECT id, event_type, severity, created_at, assigned_to, description
FROM app.events
WHERE tenant_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'
  AND severity >= 4
  AND status NOT IN ('RESOLVED', 'CLOSED')
ORDER BY created_at ASC
LIMIT 20;

-- Q5: Retention Delete
-- Implement a function app.delete_old_events(p_cutoff TIMESTAMPTZ, p_batch_size INT DEFAULT 1000)
-- that deletes events older than the cutoff in batches and returns total deleted count.
