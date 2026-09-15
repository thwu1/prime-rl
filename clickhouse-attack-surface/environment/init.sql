
-- ============================================================
-- Role Setup
-- ============================================================

CREATE USER tenant_alpha WITH PASSWORD 'alpha_app_2024';
CREATE USER tenant_beta WITH PASSWORD 'beta_app_2024';
CREATE USER svc_reporting WITH PASSWORD 'rpt_svc_2024';
CREATE USER dba_admin WITH PASSWORD 'dba_master_2024' SUPERUSER;

ALTER USER postgres WITH PASSWORD 'pg_n0_d1r3ct_2024!';

CREATE DATABASE saas_platform;
\c saas_platform

CREATE SCHEMA saas;

-- ============================================================
-- Core Tables
-- ============================================================

CREATE TABLE saas.organizations (
    org_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    plan TEXT NOT NULL,
    api_secret TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);

INSERT INTO saas.organizations VALUES
    (1, 'Acme Corp', 'enterprise', 'sk_live_acme_x7y8z9', '2023-01-15'),
    (2, 'Globex Inc', 'business', 'sk_live_globex_a1b2c3', '2023-03-22'),
    (3, 'Initech', 'starter', 'sk_live_initech_m4n5o6', '2023-06-01');

CREATE TABLE saas.invoices (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES saas.organizations(org_id),
    amount NUMERIC(12,2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    description TEXT,
    created_at TIMESTAMP DEFAULT now()
);

INSERT INTO saas.invoices (org_id, amount, status, description) VALUES
    (1, 15000.00, 'paid', 'Annual enterprise license'),
    (1, 2500.00, 'pending', 'Add-on: advanced analytics'),
    (1, 7800.00, 'paid', 'Professional services'),
    (2, 8000.00, 'paid', 'Quarterly subscription'),
    (2, 12000.00, 'overdue', 'Enterprise tier upgrade'),
    (2, 500.00, 'paid', 'Priority support'),
    (2, 3200.00, 'paid', 'Custom integration'),
    (3, 1200.00, 'paid', 'Monthly starter plan'),
    (3, 450.00, 'pending', 'Storage add-on');

CREATE TABLE saas.system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT now()
);

INSERT INTO saas.system_config VALUES
    ('db_replica_host', 'replica.internal:5432', 'Read replica connection', now()),
    ('db_replica_user', 'repl_user', 'Replica username', now()),
    ('db_replica_password', 'R3pl1c4_P@ss_2024!', 'Replica password - ROTATE QUARTERLY', now()),
    ('redis_url', 'redis://cache.internal:6379/0', 'Cache cluster connection', now()),
    ('smtp_password', 'Sm7p_S3nd3r_K3y!', 'Email service credentials', now()),
    ('app_version', '2.4.1', 'Current application version', now()),
    ('maintenance_window', 'Sunday 02:00-04:00 UTC', 'Scheduled maintenance', now()),
    ('max_tenants', '500', 'Platform capacity limit', now());

-- Decoy table for realism
CREATE TABLE saas.activity_log (
    id SERIAL PRIMARY KEY,
    org_id INTEGER,
    user_email TEXT,
    action TEXT NOT NULL,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT now()
);

INSERT INTO saas.activity_log (org_id, user_email, action, details)
SELECT
    (random() * 2 + 1)::int,
    'user' || n || '@example.com',
    (ARRAY['login', 'logout', 'view_report', 'export_data', 'update_settings'])[floor(random()*5+1)::int],
    json_build_object('ip', '10.0.' || (random()*255)::int || '.' || (random()*255)::int)::jsonb,
    now() - (random() * interval '90 days')
FROM generate_series(1, 200) AS n;

-- ============================================================
-- Row-Level Security
-- ============================================================

ALTER TABLE saas.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.activity_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_tenant_isolation ON saas.organizations
    FOR ALL TO PUBLIC
    USING (
        (current_user = 'tenant_alpha' AND org_id = 1) OR
        (current_user = 'tenant_beta' AND org_id = 2) OR
        current_user IN ('svc_reporting', 'dba_admin', 'postgres')
    );

CREATE POLICY invoice_tenant_isolation ON saas.invoices
    FOR ALL TO PUBLIC
    USING (
        (current_user = 'tenant_alpha' AND org_id = 1) OR
        (current_user = 'tenant_beta' AND org_id = 2) OR
        current_user IN ('svc_reporting', 'dba_admin', 'postgres')
    );

CREATE POLICY activity_tenant_isolation ON saas.activity_log
    FOR ALL TO PUBLIC
    USING (
        (current_user = 'tenant_alpha' AND org_id = 1) OR
        (current_user = 'tenant_beta' AND org_id = 2) OR
        current_user IN ('svc_reporting', 'dba_admin', 'postgres')
    );

-- ============================================================
-- Access Grants
-- ============================================================

GRANT USAGE ON SCHEMA saas TO tenant_alpha, tenant_beta, svc_reporting;
GRANT SELECT ON saas.organizations, saas.invoices, saas.activity_log TO tenant_alpha, tenant_beta;
GRANT SELECT ON saas.organizations, saas.invoices, saas.activity_log, saas.system_config TO svc_reporting;

-- V5 vulnerability: tenant_alpha should NOT have SELECT on system_config
GRANT SELECT ON saas.system_config TO tenant_alpha;

-- V3 vulnerability: tenant_alpha should NOT have CREATE on saas schema
GRANT CREATE ON SCHEMA saas TO tenant_alpha;

-- ============================================================
-- Utility Functions (containing vulnerabilities V1, V2, V4)
-- ============================================================

-- V1: SECURITY DEFINER function bypasses RLS because it runs as postgres (superuser)
-- Any tenant calling this with another tenant's org_id gets their financial data
CREATE OR REPLACE FUNCTION saas.monthly_summary(target_org INTEGER)
RETURNS TABLE(total_revenue NUMERIC, invoice_count BIGINT, avg_amount NUMERIC)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT
        COALESCE(SUM(i.amount), 0)::NUMERIC AS total_revenue,
        COUNT(*)::BIGINT AS invoice_count,
        COALESCE(AVG(i.amount), 0)::NUMERIC AS avg_amount
    FROM saas.invoices i
    WHERE i.org_id = target_org AND i.status = 'paid';
END;
$$;

GRANT EXECUTE ON FUNCTION saas.monthly_summary(INTEGER) TO tenant_alpha, tenant_beta, svc_reporting;

-- V2: SECURITY DEFINER function without pinned search_path
-- Attacker can shadow built-in functions (round, etc.) in public schema
CREATE OR REPLACE FUNCTION saas.format_currency(amt NUMERIC)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    result TEXT;
BEGIN
    result := '$' || round(amt, 2)::TEXT;
    RETURN result;
END;
$$;

GRANT EXECUTE ON FUNCTION saas.format_currency(NUMERIC) TO tenant_alpha, tenant_beta, svc_reporting;

-- V4: File read function with bypassable path whitelist
-- LIKE '/backups/%' does not prevent path traversal via '../'
CREATE OR REPLACE FUNCTION saas.export_backup(filepath TEXT)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF filepath NOT LIKE '/backups/%' THEN
        RAISE EXCEPTION 'Access denied: path must be under /backups/';
    END IF;
    RETURN pg_read_file(filepath);
END;
$$;

GRANT EXECUTE ON FUNCTION saas.export_backup(TEXT) TO svc_reporting;
