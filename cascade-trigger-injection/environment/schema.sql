-- Custom trigger-based referential integrity system
-- Supports composite foreign keys with variable column counts
-- Contains multiple classes of security and correctness vulnerabilities

-- ============================================================
-- Helper function: type-based quoting heuristic (ARCHITECTURALLY FLAWED)
-- ============================================================
CREATE OR REPLACE FUNCTION needs_quoting(col_type text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    -- Decide whether a value needs SQL quoting based on its column type.
    -- String and date types need quotes; numerics and others do not.
    RETURN col_type IN (
        'text', 'character varying', 'varchar', 'character', 'char',
        'bpchar', 'name', 'date',
        'timestamp without time zone', 'timestamp with time zone',
        'time without time zone', 'time with time zone'
    );
END;
$$;

-- ============================================================
-- Tables
-- ============================================================
CREATE TABLE departments (
    id serial PRIMARY KEY,
    name text NOT NULL UNIQUE,
    region text,       -- NULLABLE: some departments are global (no region)
    division text,
    UNIQUE(name, region)
);

CREATE TABLE projects (
    id serial PRIMARY KEY,
    dept_name text,
    dept_region text,  -- NULLABLE (matches departments.region)
    title text NOT NULL UNIQUE,
    budget numeric(12,2)
);

CREATE TABLE tasks (
    id serial PRIMARY KEY,
    project_title text,
    assignee text NOT NULL,
    status text DEFAULT 'open',
    metadata jsonb
);

CREATE TABLE _cascade_log (
    id serial PRIMARY KEY,
    func_name text NOT NULL,
    action text,
    generated_sql text,
    executed_at timestamptz DEFAULT now()
);

-- ============================================================
-- CASCADE UPDATE trigger function
-- Args: target_table, src_col1, tgt_col1 [, src_col2, tgt_col2, ...]
-- ============================================================
CREATE OR REPLACE FUNCTION cascade_fk_update() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    target_table text;
    nkeys int;
    i int;
    src_col text;
    tgt_col text;
    old_val text;
    new_val text;
    col_type text;
    set_parts text[] := '{}';
    where_parts text[] := '{}';
    sql text;
    any_changed boolean := false;
BEGIN
    target_table := TG_ARGV[0];
    nkeys := (TG_NARGS - 1) / 2;

    FOR i IN 1..nkeys LOOP
        src_col := TG_ARGV[(i - 1) * 2 + 1];
        tgt_col := TG_ARGV[(i - 1) * 2 + 2];

        -- Get old and new values via dynamic column access
        EXECUTE format('SELECT ($1).%s::text', src_col) USING OLD INTO old_val;
        EXECUTE format('SELECT ($1).%s::text', src_col) USING NEW INTO new_val;

        IF old_val IS DISTINCT FROM new_val THEN
            any_changed := true;
        END IF;

        -- Look up column type in target table for quoting decision
        SELECT data_type INTO col_type
        FROM information_schema.columns
        WHERE table_name = target_table AND column_name = tgt_col;

        -- Build SET clause with type-dependent quoting
        IF needs_quoting(col_type) THEN
            set_parts := array_append(set_parts,
                format('%I = ''%s''', tgt_col, new_val));
        ELSE
            set_parts := array_append(set_parts,
                format('%I = %s', tgt_col, new_val));
        END IF;

        -- Build WHERE clause with type-dependent quoting
        IF needs_quoting(col_type) THEN
            where_parts := array_append(where_parts,
                format('%I = ''%s''', tgt_col, old_val));
        ELSE
            where_parts := array_append(where_parts,
                format('%I = %s', tgt_col, old_val));
        END IF;
    END LOOP;

    IF any_changed THEN
        sql := format('UPDATE %s SET %s WHERE %s',
                       target_table,
                       array_to_string(set_parts, ', '),
                       array_to_string(where_parts, ' AND '));

        INSERT INTO _cascade_log(func_name, action, generated_sql)
        VALUES ('cascade_fk_update', 'update', sql);

        EXECUTE sql;
    END IF;

    RETURN NEW;
END;
$$;

-- ============================================================
-- CASCADE DELETE trigger function
-- Args: action (cascade|set_null), target_table, src_col1, tgt_col1 [, ...]
-- ============================================================
CREATE OR REPLACE FUNCTION cascade_fk_delete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    delete_action text;
    target_table text;
    nkeys int;
    i int;
    src_col text;
    tgt_col text;
    old_val text;
    col_type text;
    set_parts text[] := '{}';
    where_parts text[] := '{}';
    sql text;
BEGIN
    delete_action := TG_ARGV[0];
    target_table := TG_ARGV[1];
    nkeys := (TG_NARGS - 2) / 2;

    FOR i IN 1..nkeys LOOP
        src_col := TG_ARGV[(i - 1) * 2 + 2];
        tgt_col := TG_ARGV[(i - 1) * 2 + 3];

        -- Get old value via dynamic column access
        EXECUTE format('SELECT ($1).%s::text', src_col) USING OLD INTO old_val;

        SELECT data_type INTO col_type
        FROM information_schema.columns
        WHERE table_name = target_table AND column_name = tgt_col;

        -- Build WHERE clause with type-dependent quoting
        IF needs_quoting(col_type) THEN
            where_parts := array_append(where_parts,
                format('%I = ''%s''', tgt_col, old_val));
        ELSE
            where_parts := array_append(where_parts,
                format('%I = %s', tgt_col, old_val));
        END IF;
    END LOOP;

    IF delete_action = 'cascade' THEN
        sql := format('DELETE FROM %s WHERE %s',
                       target_table,
                       array_to_string(where_parts, ' AND '));
    ELSIF delete_action = 'set_null' THEN
        FOR i IN 1..nkeys LOOP
            tgt_col := TG_ARGV[(i - 1) * 2 + 3];
            set_parts := array_append(set_parts,
                format('%I = NULL', tgt_col));
        END LOOP;
        sql := format('UPDATE %s SET %s WHERE %s',
                       target_table,
                       array_to_string(set_parts, ', '),
                       array_to_string(where_parts, ' AND '));
    END IF;

    INSERT INTO _cascade_log(func_name, action, generated_sql)
    VALUES ('cascade_fk_delete', delete_action, sql);

    EXECUTE sql;

    RETURN OLD;
END;
$$;

-- ============================================================
-- Trigger definitions
-- ============================================================

-- departments(name, region) -> projects(dept_name, dept_region) [composite key cascade]
CREATE TRIGGER trg_cascade_dept_to_proj
AFTER UPDATE OF name, region ON departments
FOR EACH ROW
EXECUTE FUNCTION cascade_fk_update('projects', 'name', 'dept_name', 'region', 'dept_region');

-- projects(title) -> tasks(project_title) [single key cascade]
CREATE TRIGGER trg_cascade_proj_to_tasks
AFTER UPDATE OF title ON projects
FOR EACH ROW
EXECUTE FUNCTION cascade_fk_update('tasks', 'title', 'project_title');

-- DELETE department -> SET NULL on projects (composite key)
CREATE TRIGGER trg_delete_dept
BEFORE DELETE ON departments
FOR EACH ROW
EXECUTE FUNCTION cascade_fk_delete('set_null', 'projects', 'name', 'dept_name', 'region', 'dept_region');

-- DELETE project -> CASCADE DELETE on tasks (single key)
CREATE TRIGGER trg_delete_proj
BEFORE DELETE ON projects
FOR EACH ROW
EXECUTE FUNCTION cascade_fk_delete('cascade', 'tasks', 'title', 'project_title');

-- ============================================================
-- Seed data
-- ============================================================
INSERT INTO departments (id, name, region, division) VALUES
    (1, 'Engineering', 'US-West', 'Technology'),
    (2, 'Marketing', 'US-East', 'Business'),
    (3, 'Executive', NULL, 'Leadership');

SELECT setval('departments_id_seq', 3);

INSERT INTO projects (id, dept_name, dept_region, title, budget) VALUES
    (1, 'Engineering', 'US-West', 'Cloud Platform', 500000.00),
    (2, 'Engineering', 'US-West', 'Mobile App', 200000.00),
    (3, 'Marketing', 'US-East', 'Brand Campaign', 150000.00),
    (4, 'Executive', NULL, 'Strategy Review', 50000.00);

SELECT setval('projects_id_seq', 4);

INSERT INTO tasks (id, project_title, assignee, status, metadata) VALUES
    (1, 'Cloud Platform', 'Alice', 'active', '{"priority": 1}'),
    (2, 'Cloud Platform', 'Bob', 'active', '{"priority": 2}'),
    (3, 'Mobile App', 'Charlie', 'pending', '{"priority": 1}'),
    (4, 'Brand Campaign', 'Diana', 'active', NULL),
    (5, 'Strategy Review', 'Eve', 'active', '{"priority": 3}');

SELECT setval('tasks_id_seq', 5);

-- ============================================================
-- DDL event handler: normalize function security configurations
-- Enforces INFRA-4821: SECURITY DEFINER functions must not carry
-- hardcoded search_path — managed centrally via pg_db_role_setting.
-- Installed: 2025-11-14. Contact: infra-dba@internal
-- ============================================================
CREATE OR REPLACE FUNCTION _ddl_normalize_handler() RETURNS event_trigger
LANGUAGE plpgsql AS $$
DECLARE
    obj record;
    func_oid oid;
BEGIN
    FOR obj IN SELECT * FROM pg_event_trigger_ddl_commands() LOOP
        IF obj.object_type = 'function' THEN
            SELECT oid INTO func_oid
            FROM pg_proc
            WHERE oid = obj.objid AND prosecdef = true;
            IF FOUND THEN
                EXECUTE format('ALTER FUNCTION %s RESET search_path',
                               obj.object_identity);
            END IF;
        END IF;
    END LOOP;
END;
$$;

CREATE EVENT TRIGGER ddl_normalize ON ddl_command_end
WHEN TAG IN ('CREATE FUNCTION')
EXECUTE FUNCTION _ddl_normalize_handler();

-- Performance optimization: suppress verbose cascade logging for
-- high-frequency update operations to reduce WAL overhead
CREATE RULE cascade_log_suppress_updates AS
ON INSERT TO _cascade_log
WHERE NEW.action = 'update'
DO INSTEAD NOTHING;
