
-- Event monitoring system schema (read-only reference)
-- Table contains ~500K rows across 10 tenants
-- No secondary indexes exist yet — you must create them.

CREATE TABLE app.events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL,
    event_type VARCHAR(50) NOT NULL,   -- Values: ALERT, INCIDENT, CHANGE, MAINTENANCE, DEPLOYMENT
    severity INT NOT NULL,             -- 1 (low) to 5 (critical); distribution weighted toward lower
    created_at TIMESTAMPTZ NOT NULL,   -- Range: 2024-01-01 to 2024-07-01
    resolved_at TIMESTAMPTZ,           -- NULL for unresolved events; set for RESOLVED/CLOSED
    status VARCHAR(20) NOT NULL,       -- Values: OPEN, ACKNOWLEDGED, IN_PROGRESS, RESOLVED, CLOSED
    source_system VARCHAR(50) NOT NULL,-- Values: prometheus, grafana, datadog, pagerduty, cloudwatch, nagios, splunk
    description TEXT,
    assigned_to UUID                   -- NULL if unassigned; 5 possible assignee UUIDs
);

-- Approximate distribution per tenant (~50K rows each):
--   status: 45% RESOLVED, 10% CLOSED, 15% OPEN, 15% ACKNOWLEDGED, 15% IN_PROGRESS
--   severity: 35% sev-1, 25% sev-2, 20% sev-3, 13% sev-4, 7% sev-5
--   event_type: 20% each (uniform across 5 types)
