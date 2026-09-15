
-- Simulated Supabase auth infrastructure and multi-tenant application schema.
-- This file is CORRECT. Do not modify.

---------------------------------------------
-- SCHEMAS
---------------------------------------------
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS private;

---------------------------------------------
-- ROLES
---------------------------------------------
DO $$ BEGIN CREATE ROLE anon NOLOGIN NOINHERIT; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated NOLOGIN NOINHERIT; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

---------------------------------------------
-- AUTH SIMULATION (mimics Supabase auth)
---------------------------------------------
CREATE TABLE IF NOT EXISTS auth.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text UNIQUE,
    raw_user_meta_data jsonb DEFAULT '{}',
    raw_app_meta_data jsonb DEFAULT '{}'
);

-- auth.uid(): returns the current user's UUID from JWT claims
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE
AS $$ SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid; $$;

-- auth.jwt(): returns the full JWT claims as jsonb
CREATE OR REPLACE FUNCTION auth.jwt() RETURNS jsonb
LANGUAGE sql STABLE
AS $$ SELECT COALESCE(NULLIF(current_setting('request.jwt.claims', true), ''), '{}')::jsonb; $$;

---------------------------------------------
-- SCHEMA GRANTS
---------------------------------------------
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
GRANT USAGE ON SCHEMA private TO service_role;

---------------------------------------------
-- APPLICATION TABLES
---------------------------------------------
CREATE TABLE organizations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    slug text UNIQUE NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE org_members (
    org_id uuid REFERENCES organizations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('owner','admin','member','viewer')),
    joined_at timestamptz DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

CREATE TABLE projects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid REFERENCES organizations(id) ON DELETE CASCADE,
    name text NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
    title text NOT NULL,
    content text DEFAULT '',
    classification text NOT NULL DEFAULT 'internal' CHECK (classification IN ('public','internal','confidential')),
    created_by uuid NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE document_shares (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid REFERENCES documents(id) ON DELETE CASCADE,
    shared_with uuid NOT NULL,
    permission text NOT NULL CHECK (permission IN ('read','write')),
    shared_by uuid NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name text NOT NULL,
    action text NOT NULL,
    row_id uuid,
    actor_id uuid,
    details jsonb DEFAULT '{}',
    created_at timestamptz DEFAULT now()
);

---------------------------------------------
-- TABLE GRANTS
---------------------------------------------
GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon;
GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;

---------------------------------------------
-- ENABLE ROW LEVEL SECURITY
---------------------------------------------
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_shares ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
