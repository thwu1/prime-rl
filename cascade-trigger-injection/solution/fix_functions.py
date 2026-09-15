#!/usr/bin/env python3
"""
Analyze buggy cascade trigger functions in PostgreSQL, identify all
vulnerability classes and environmental interference, generate exploitation
proof and corrected definitions, and apply fixes to the running database.
"""

import psycopg2
import sys


VULNERABILITY_ANALYSIS_SQL = r"""-- =====================================================
-- Vulnerability Analysis: Composite-Key Cascade System
-- =====================================================
-- Run against UNFIXED system to demonstrate exploits.

-- =====================================================
-- Vulnerability 1: SQL Injection via Dynamic Value Interpolation
-- =====================================================
-- The cascade functions use format('... = ''%s''', value) for WHERE and SET
-- clauses. The %s specifier performs NO escaping, so embedded single quotes
-- in OLD or NEW values break out of the string literal, enabling SQL injection.
--
-- When dept_name = "injected' OR '1'='1", the generated WHERE becomes:
--   WHERE dept_name = 'injected' OR '1'='1' AND dept_region = 'US-West'
-- Due to operator precedence (AND > OR), this matches ALL US-West projects.

INSERT INTO departments (id, name, region, division)
VALUES (100, 'injected'' OR ''1''=''1', 'US-West', 'Test');
INSERT INTO projects (id, dept_name, dept_region, title, budget)
VALUES (100, 'injected'' OR ''1''=''1', 'US-West', 'ExploitProject', 1.00);

SELECT 'BEFORE WHERE injection attack:' AS label;
SELECT id, dept_name, dept_region FROM projects ORDER BY id;

-- This UPDATE triggers the cascade. The WHERE clause is injected.
UPDATE departments SET name = 'clean' WHERE id = 100;

SELECT 'AFTER WHERE injection attack:' AS label;
SELECT id, dept_name, dept_region FROM projects ORDER BY id;
-- Projects 1,2 (Engineering, US-West) are now corrupted to 'clean'!

-- =====================================================
-- Vulnerability 2: NULL Composite Key Cascade Bypass
-- =====================================================
-- format('%s', NULL) produces empty string in PL/pgSQL. The generated WHERE
-- becomes: WHERE dept_region = '' (comparing to empty string, not NULL).
-- Since NULL != '' in SQL, rows with NULL in the composite key column are
-- silently skipped, leaving orphaned child records.

SET session_replication_role = 'replica';
DELETE FROM _cascade_log; DELETE FROM tasks;
DELETE FROM projects; DELETE FROM departments;
SET session_replication_role = 'origin';

INSERT INTO departments (id, name, region, division)
VALUES (3, 'Executive', NULL, 'Leadership');
INSERT INTO projects (id, dept_name, dept_region, title, budget)
VALUES (4, 'Executive', NULL, 'Strategy Review', 50000.00);

SELECT 'BEFORE NULL bypass:' AS label;
SELECT id, dept_name, dept_region FROM projects WHERE id = 4;

UPDATE departments SET name = 'Exec Board' WHERE id = 3;

SELECT 'AFTER NULL bypass (should show Exec Board):' AS label;
SELECT id, dept_name, dept_region FROM projects WHERE id = 4;
-- dept_name still shows 'Executive' — cascade silently failed!

SELECT 'Generated SQL showing the bug:' AS label;
SELECT generated_sql FROM _cascade_log ORDER BY id DESC LIMIT 1;
-- NOTE: The _cascade_log may show NO entries for update cascades due to a
-- suppression RULE — this is Vulnerability 3b below.

-- =====================================================
-- Vulnerability 3: Environmental Interference
-- =====================================================
-- 3a: DDL Event Trigger silently strips search_path
-- The database has an event trigger 'ddl_normalize' (handler:
-- _ddl_normalize_handler) that fires on ddl_command_end for CREATE FUNCTION.
-- For any SECURITY DEFINER function, it runs:
--   ALTER FUNCTION ... RESET search_path
-- This silently removes the search_path setting from SECURITY DEFINER
-- functions after CREATE OR REPLACE, leaving them vulnerable to search_path
-- hijacking. The event trigger's comment claims this is per INFRA-4821 for
-- "pg14->pg16 compatibility," but this rationale is incorrect — SECURITY
-- DEFINER functions MUST set search_path to prevent privilege escalation.

-- Demonstrate: verify the event trigger exists
SELECT evtname, evtevent, evtenabled
FROM pg_event_trigger WHERE evtname = 'ddl_normalize';

-- Demonstrate: create a test SECURITY DEFINER function with search_path
CREATE OR REPLACE FUNCTION _test_secdef_probe() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$ BEGIN NULL; END; $$;

-- Verify: search_path was silently stripped by the event trigger
SELECT proname, prosecdef,
       proconfig IS NULL AS search_path_stripped
FROM pg_proc WHERE proname = '_test_secdef_probe';
-- prosecdef = true, search_path_stripped = true (proconfig is NULL)

DROP FUNCTION IF EXISTS _test_secdef_probe();

-- 3b: RULE on _cascade_log suppresses UPDATE cascade logging
-- A PostgreSQL RULE named 'cascade_log_suppress_updates' on _cascade_log
-- silently discards INSERT operations where action = 'update'. This means
-- the cascade log shows NO entries for UPDATE cascades, misleading anyone
-- who checks the log to debug cascade behavior.

SELECT rulename, tablename
FROM pg_rules WHERE tablename = '_cascade_log';
-- Shows: cascade_log_suppress_updates
"""


FIXED_FUNCTIONS_SQL = r"""-- =====================================================
-- Fixed Cascade Trigger Functions
-- =====================================================
-- Fixes applied:
-- 1. Dropped needs_quoting() — type-based quoting is architecturally wrong
-- 2. Replaced ''%s'' with %L for all value interpolation (type-agnostic)
-- 3. Replaced %s with %I for all identifier interpolation
-- 4. Replaced = with IS NOT DISTINCT FROM for NULL-safe composite keys
-- 5. Added SET search_path to SECURITY DEFINER functions
-- 6. Removed information_schema type lookups (no longer needed)
-- 7. %I used for table names in EXECUTE statements

-- Drop the flawed type-detection helper
DROP FUNCTION IF EXISTS needs_quoting(text);

-- Fixed CASCADE UPDATE trigger function
CREATE OR REPLACE FUNCTION cascade_fk_update() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    target_table text;
    nkeys int;
    i int;
    src_col text;
    tgt_col text;
    old_val text;
    new_val text;
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

        EXECUTE format('SELECT ($1).%I::text', src_col) USING OLD INTO old_val;
        EXECUTE format('SELECT ($1).%I::text', src_col) USING NEW INTO new_val;

        IF old_val IS DISTINCT FROM new_val THEN
            any_changed := true;
        END IF;

        set_parts := array_append(set_parts,
            format('%I = %L', tgt_col, new_val));

        where_parts := array_append(where_parts,
            format('%I IS NOT DISTINCT FROM %L', tgt_col, old_val));
    END LOOP;

    IF any_changed THEN
        sql := format('UPDATE %I SET %s WHERE %s',
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

-- Fixed CASCADE DELETE trigger function
CREATE OR REPLACE FUNCTION cascade_fk_delete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    delete_action text;
    target_table text;
    nkeys int;
    i int;
    src_col text;
    tgt_col text;
    old_val text;
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

        EXECUTE format('SELECT ($1).%I::text', src_col) USING OLD INTO old_val;

        where_parts := array_append(where_parts,
            format('%I IS NOT DISTINCT FROM %L', tgt_col, old_val));
    END LOOP;

    IF delete_action = 'cascade' THEN
        sql := format('DELETE FROM %I WHERE %s',
                       target_table,
                       array_to_string(where_parts, ' AND '));
    ELSIF delete_action = 'set_null' THEN
        FOR i IN 1..nkeys LOOP
            tgt_col := TG_ARGV[(i - 1) * 2 + 3];
            set_parts := array_append(set_parts,
                format('%I = NULL', tgt_col));
        END LOOP;
        sql := format('UPDATE %I SET %s WHERE %s',
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
"""


def main():
    conn = psycopg2.connect(dbname="appdb", user="postgres", host="localhost")
    conn.autocommit = True
    cur = conn.cursor()

    # ── Step 1: Analyze current function sources ──
    vulnerabilities = []
    for func_name in ("cascade_fk_update", "cascade_fk_delete"):
        cur.execute(
            "SELECT prosrc FROM pg_proc WHERE proname = %s", (func_name,))
        row = cur.fetchone()
        if not row:
            continue
        src = row[0]
        if "''%s''" in src:
            vulnerabilities.append(
                f"{func_name}: SQL injection via manual quote wrapping")
        if "needs_quoting" in src.lower():
            vulnerabilities.append(
                f"{func_name}: architecturally flawed type-based quoting")
        if "information_schema" in src.lower():
            vulnerabilities.append(
                f"{func_name}: type detection via information_schema lookup")
        if "($1).%s" in src:
            vulnerabilities.append(
                f"{func_name}: identifier injection via format %s for columns")

    # Check SECURITY DEFINER search_path
    cur.execute("""
        SELECT proname, prosecdef, proconfig
        FROM pg_proc
        WHERE proname IN ('cascade_fk_update', 'cascade_fk_delete')
    """)
    for row in cur.fetchall():
        name, secdef, config = row
        if secdef:
            config = config or []
            if not any("search_path" in str(c) for c in config):
                vulnerabilities.append(
                    f"{name}: SECURITY DEFINER without search_path")

    print(f"Identified {len(vulnerabilities)} vulnerability instances:")
    for v in vulnerabilities:
        print(f"  - {v}")

    # ── Step 2: Detect and remove environmental interference ──

    # 2a: Check for DDL event triggers that silently modify functions
    cur.execute("""
        SELECT et.evtname, p.proname
        FROM pg_event_trigger et
        JOIN pg_proc p ON et.evtfoid = p.oid
        WHERE et.evtevent = 'ddl_command_end' AND et.evtenabled != 'D'
    """)
    event_triggers = cur.fetchall()
    if event_triggers:
        print(f"\nFound interfering DDL event triggers:")
        for et_name, handler_name in event_triggers:
            print(f"  Dropping event trigger: {et_name} (handler: {handler_name})")
            cur.execute("DROP EVENT TRIGGER IF EXISTS %s" % et_name)
            cur.execute("DROP FUNCTION IF EXISTS %s() CASCADE" % handler_name)
        print("  Environmental DDL interference removed.")
    else:
        print("\nNo interfering DDL event triggers found.")

    # 2b: Check for rules on _cascade_log that suppress logging
    cur.execute("SELECT rulename FROM pg_rules WHERE tablename = '_cascade_log'")
    rules = [r[0] for r in cur.fetchall()]
    if rules:
        print(f"Found log suppression rules on _cascade_log: {rules}")
        for rule in rules:
            cur.execute("DROP RULE IF EXISTS %s ON _cascade_log" % rule)
            print(f"  Dropped rule: {rule}")
    else:
        print("No log suppression rules found.")

    # ── Step 3: Write vulnerability analysis SQL ──
    with open("/app/vulnerability_analysis.sql", "w") as f:
        f.write(VULNERABILITY_ANALYSIS_SQL)
    print("\nWrote /app/vulnerability_analysis.sql")

    # ── Step 4: Write fixed functions SQL ──
    with open("/app/fixed_functions.sql", "w") as f:
        f.write(FIXED_FUNCTIONS_SQL)
    print("Wrote /app/fixed_functions.sql")

    # ── Step 5: Apply the fixed functions (event trigger already removed) ──
    cur.execute(FIXED_FUNCTIONS_SQL)
    print("Applied fixed functions to database.")

    # ── Step 6: Comprehensive verification ──
    print("\n=== Post-fix verification ===")
    all_ok = True

    # 6a: Function source code quality
    cur.execute(
        "SELECT prosrc FROM pg_proc WHERE proname = 'cascade_fk_update'")
    src = cur.fetchone()[0]
    code_ok = (
        "''%s''" not in src
        and "needs_quoting" not in src.lower()
        and "information_schema" not in src.lower()
    )
    if not code_ok:
        print("  FAIL: Function source still contains vulnerable patterns")
        all_ok = False
    else:
        print("  PASS: Function source code is clean")

    # 6b: search_path persistence
    for func_name in ("cascade_fk_update", "cascade_fk_delete"):
        cur.execute("""
            SELECT proconfig FROM pg_proc
            WHERE proname = %s AND prosecdef = true
        """, (func_name,))
        row = cur.fetchone()
        config = row[0] if row else []
        sp_ok = any("search_path" in str(c) for c in (config or []))
        if not sp_ok:
            print(f"  FAIL: {func_name} search_path not set")
            all_ok = False
        else:
            print(f"  PASS: {func_name} search_path persists")

    # 6c: No remaining event triggers
    cur.execute("""
        SELECT count(*) FROM pg_event_trigger
        WHERE evtevent = 'ddl_command_end' AND evtenabled != 'D'
    """)
    et_count = cur.fetchone()[0]
    if et_count > 0:
        print(f"  FAIL: {et_count} interfering event triggers remain")
        all_ok = False
    else:
        print("  PASS: No interfering event triggers")

    # 6d: No remaining log suppression rules
    cur.execute("SELECT count(*) FROM pg_rules WHERE tablename = '_cascade_log'")
    rule_count = cur.fetchone()[0]
    if rule_count > 0:
        print(f"  FAIL: {rule_count} log suppression rules remain")
        all_ok = False
    else:
        print("  PASS: No log suppression rules")

    print(f"\nOverall: {'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'}")
    conn.close()

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
