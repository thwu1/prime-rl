
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE app.events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    severity INT NOT NULL CHECK (severity BETWEEN 1 AND 5),
    created_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL,
    source_system VARCHAR(50) NOT NULL,
    description TEXT,
    assigned_to UUID
);
