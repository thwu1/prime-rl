-- temporal_solution.sql — Complete correct implementation of temporal versioning
--

CREATE SCHEMA IF NOT EXISTS temporal;

CREATE TABLE IF NOT EXISTS temporal.tracked_tables (
    table_oid          oid PRIMARY KEY,
    schema_name        text NOT NULL,
    table_name         text NOT NULL,
    history_table_name text NOT NULL,
    pk_columns         text[] NOT NULL,
    all_columns        text[] NOT NULL,
    enabled_at         timestamptz NOT NULL DEFAULT now()
);

-- ── enable_versioning ────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION temporal.enable_versioning(target_table regclass)
RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_schema          text;
    v_table           text;
    v_history_table   text;
    v_pk_columns      text[];
    v_all_columns     text[];
    v_col_defs        text[];
    v_col             record;
    v_trigger_fn_name text;
    v_col_list        text;
    v_new_col_list    text;
    v_pk_where_old    text;
    v_pk_idx_cols     text;
BEGIN
    -- Resolve schema and table name
    SELECT n.nspname, c.relname
      INTO v_schema, v_table
      FROM pg_class c
      JOIN pg_namespace n ON c.relnamespace = n.oid
     WHERE c.oid = target_table;

    -- Get primary-key columns (ordered)
    SELECT array_agg(a.attname::text ORDER BY array_position(con.conkey, a.attnum))
      INTO v_pk_columns
      FROM pg_constraint con
      JOIN pg_attribute a ON a.attrelid = con.conrelid
                         AND a.attnum = ANY(con.conkey)
     WHERE con.conrelid = target_table
       AND con.contype  = 'p';

    IF v_pk_columns IS NULL OR array_length(v_pk_columns, 1) IS NULL THEN
        RAISE EXCEPTION 'Table % has no primary key. Temporal versioning requires a primary key.', target_table;
    END IF;

    IF EXISTS (SELECT 1 FROM temporal.tracked_tables WHERE table_oid = target_table) THEN
        RAISE EXCEPTION 'Table % is already tracked by temporal versioning.', target_table;
    END IF;

    -- Collect every user column with its type
    v_all_columns := ARRAY[]::text[];
    v_col_defs    := ARRAY[]::text[];
    FOR v_col IN
        SELECT a.attname::text                                 AS col_name,
               pg_catalog.format_type(a.atttypid, a.atttypmod) AS col_type
          FROM pg_attribute a
         WHERE a.attrelid = target_table
           AND a.attnum > 0
           AND NOT a.attisdropped
         ORDER BY a.attnum
    LOOP
        v_all_columns := array_append(v_all_columns, v_col.col_name);
        v_col_defs    := array_append(v_col_defs,
                            format('%I %s', v_col.col_name, v_col.col_type));
    END LOOP;

    -- Create history table
    v_history_table := v_table || '_history';
    EXECUTE format(
        'CREATE TABLE %I.%I (%s, '
        '_valid_from timestamptz NOT NULL, '
        '_valid_to   timestamptz NOT NULL)',
        v_schema, v_history_table,
        array_to_string(v_col_defs, ', ')
    );

    -- Index: PK + temporal bounds
    v_pk_idx_cols := (SELECT string_agg(format('%I', c), ', ')
                        FROM unnest(v_pk_columns) AS c);
    EXECUTE format('CREATE INDEX ON %I.%I (%s, _valid_from, _valid_to)',
                   v_schema, v_history_table, v_pk_idx_cols);

    -- Build SQL fragments for the trigger body
    v_col_list     := (SELECT string_agg(format('%I', c), ', ')
                         FROM unnest(v_all_columns) AS c);
    v_new_col_list := (SELECT string_agg(format('NEW.%I', c), ', ')
                         FROM unnest(v_all_columns) AS c);
    -- FIX: Use ALL PK columns in WHERE clause, not just the first
    v_pk_where_old := (SELECT string_agg(format('%I = OLD.%I', c, c), ' AND ')
                         FROM unnest(v_pk_columns) AS c);

    -- Generate per-table trigger function
    v_trigger_fn_name := format('_trg_%s_%s', v_schema, v_table);

    EXECUTE format($trg$
        CREATE OR REPLACE FUNCTION temporal.%1$I() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        DECLARE
            _ts timestamptz := clock_timestamp();
        BEGIN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO %2$I.%3$I (%4$s, _valid_from, _valid_to)
                VALUES (%5$s, _ts, 'infinity'::timestamptz);
                RETURN NEW;
            ELSIF TG_OP = 'UPDATE' THEN
                UPDATE %2$I.%3$I SET _valid_to = _ts
                WHERE %6$s AND _valid_to = 'infinity'::timestamptz;
                INSERT INTO %2$I.%3$I (%4$s, _valid_from, _valid_to)
                VALUES (%5$s, _ts, 'infinity'::timestamptz);
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE %2$I.%3$I SET _valid_to = _ts
                WHERE %6$s AND _valid_to = 'infinity'::timestamptz;
                RETURN OLD;
            END IF;
            RETURN NULL;
        END;
        $fn$;
    $trg$,
        v_trigger_fn_name,   -- %1  trigger function name (unqualified)
        v_schema,            -- %2  schema
        v_history_table,     -- %3  history table name
        v_col_list,          -- %4  "col1", "col2", ...
        v_new_col_list,      -- %5  NEW."col1", NEW."col2", ...
        v_pk_where_old       -- %6  "pk1" = OLD."pk1" AND ...
    );

    -- Attach trigger
    EXECUTE format(
        'CREATE TRIGGER temporal_versioning '
        'AFTER INSERT OR UPDATE OR DELETE ON %I.%I '
        'FOR EACH ROW EXECUTE FUNCTION temporal.%I()',
        v_schema, v_table, v_trigger_fn_name
    );

    -- FIX: Snapshot existing rows into history
    EXECUTE format(
        'INSERT INTO %I.%I (%s, _valid_from, _valid_to) '
        'SELECT %s, $1, ''infinity''::timestamptz FROM %I.%I',
        v_schema, v_history_table,
        v_col_list,
        v_col_list,
        v_schema, v_table
    ) USING clock_timestamp();

    -- Register
    INSERT INTO temporal.tracked_tables
        (table_oid, schema_name, table_name, history_table_name,
         pk_columns, all_columns)
    VALUES
        (target_table, v_schema, v_table, v_history_table,
         v_pk_columns, v_all_columns);
END;
$$;

-- ── disable_versioning ───────────────────────────────────────────────

CREATE OR REPLACE FUNCTION temporal.disable_versioning(target_table regclass)
RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_schema          text;
    v_table           text;
    v_history_table   text;
    v_trigger_fn_name text;
BEGIN
    SELECT schema_name, table_name, history_table_name
      INTO v_schema, v_table, v_history_table
      FROM temporal.tracked_tables
     WHERE table_oid = target_table;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Table % is not tracked by temporal versioning.', target_table;
    END IF;

    v_trigger_fn_name := format('_trg_%s_%s', v_schema, v_table);

    EXECUTE format('DROP TRIGGER IF EXISTS temporal_versioning ON %I.%I',
                   v_schema, v_table);
    EXECUTE format('DROP FUNCTION IF EXISTS temporal.%I()',
                   v_trigger_fn_name);
    EXECUTE format('DROP TABLE IF EXISTS %I.%I',
                   v_schema, v_history_table);

    DELETE FROM temporal.tracked_tables WHERE table_oid = target_table;
END;
$$;

-- ── table_at ─────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION temporal.table_at(
    target_table regclass,
    ts timestamptz
)
RETURNS SETOF jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_schema        text;
    v_history_table text;
    v_all_columns   text[];
    v_jsonb_args    text;
BEGIN
    SELECT schema_name, history_table_name, all_columns
      INTO v_schema, v_history_table, v_all_columns
      FROM temporal.tracked_tables
     WHERE table_oid = target_table;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Table % is not tracked by temporal versioning.', target_table;
    END IF;

    -- 'col_name', "col_name", ...
    v_jsonb_args := (
        SELECT string_agg(format('%L, %I', c, c), ', ')
          FROM unnest(v_all_columns) AS c
    );

    -- FIX: Use <= for _valid_from (not strict <)
    RETURN QUERY EXECUTE format(
        'SELECT jsonb_build_object(%s) FROM %I.%I '
        'WHERE _valid_from <= $1 AND _valid_to > $1',
        v_jsonb_args, v_schema, v_history_table
    ) USING ts;
END;
$$;

-- ── changes_between ──────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION temporal.changes_between(
    target_table regclass,
    ts1 timestamptz,
    ts2 timestamptz
)
RETURNS TABLE(operation text, pk_values jsonb, old_row jsonb, new_row jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_schema        text;
    v_history_table text;
    v_pk_columns    text[];
    v_all_columns   text[];
    v_first_pk      text;
    v_jsonb_old     text;
    v_jsonb_new     text;
    v_pk_jsonb      text;
    v_join_cond     text;
    v_sql           text;
BEGIN
    SELECT t.schema_name, t.history_table_name, t.pk_columns, t.all_columns
      INTO v_schema, v_history_table, v_pk_columns, v_all_columns
      FROM temporal.tracked_tables t
     WHERE t.table_oid = target_table;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Table % is not tracked by temporal versioning.', target_table;
    END IF;

    v_first_pk := v_pk_columns[1];

    v_jsonb_old := (
        SELECT string_agg(format('%L, o.%I', c, c), ', ')
          FROM unnest(v_all_columns) AS c
    );
    v_jsonb_new := (
        SELECT string_agg(format('%L, n.%I', c, c), ', ')
          FROM unnest(v_all_columns) AS c
    );
    v_pk_jsonb := (
        SELECT string_agg(
            format('%L, COALESCE(n.%I, o.%I)', c, c, c), ', ')
          FROM unnest(v_pk_columns) AS c
    );
    v_join_cond := (
        SELECT string_agg(format('o.%I = n.%I', c, c), ' AND ')
          FROM unnest(v_pk_columns) AS c
    );

    v_sql := format($q$
        WITH old_snap AS (
            SELECT * FROM %1$I.%2$I
             WHERE _valid_from <= $1 AND _valid_to > $1
        ),
        new_snap AS (
            SELECT * FROM %1$I.%2$I
             WHERE _valid_from <= $2 AND _valid_to > $2
        )
        SELECT
            CASE
                WHEN o.%3$I IS NULL THEN 'INSERT'
                WHEN n.%3$I IS NULL THEN 'DELETE'
                ELSE 'UPDATE'
            END::text,
            jsonb_build_object(%4$s),
            CASE WHEN o.%3$I IS NOT NULL
                 THEN jsonb_build_object(%5$s) END,
            CASE WHEN n.%3$I IS NOT NULL
                 THEN jsonb_build_object(%6$s) END
        FROM old_snap o
        FULL OUTER JOIN new_snap n ON %7$s
        WHERE o.%3$I IS NULL
           OR n.%3$I IS NULL
           OR jsonb_build_object(%5$s) IS DISTINCT FROM jsonb_build_object(%6$s)
    $q$,
        v_schema,         -- %1
        v_history_table,  -- %2
        v_first_pk,       -- %3
        v_pk_jsonb,       -- %4
        v_jsonb_old,      -- %5
        v_jsonb_new,      -- %6
        v_join_cond       -- %7
    );

    RETURN QUERY EXECUTE v_sql USING ts1, ts2;
END;
$$;

-- ── merge_history ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION temporal.merge_history(target_table regclass)
RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    v_schema        text;
    v_history_table text;
    v_pk_columns    text[];
    v_all_columns   text[];
    v_non_pk_cols   text[];
    v_col           text;
    v_pk_join       text;
    v_non_pk_eq     text;
    v_removed       integer := 0;
    v_batch         integer;
BEGIN
    SELECT t.schema_name, t.history_table_name, t.pk_columns, t.all_columns
      INTO v_schema, v_history_table, v_pk_columns, v_all_columns
      FROM temporal.tracked_tables t
     WHERE t.table_oid = target_table;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Table % is not tracked by temporal versioning.', target_table;
    END IF;

    -- Determine non-PK columns (the ones to compare for value identity)
    v_non_pk_cols := ARRAY[]::text[];
    FOREACH v_col IN ARRAY v_all_columns LOOP
        IF NOT (v_col = ANY(v_pk_columns)) THEN
            v_non_pk_cols := array_append(v_non_pk_cols, v_col);
        END IF;
    END LOOP;

    -- Build PK join for self-join: a.pk1 = b.pk1 AND a.pk2 = b.pk2 ...
    v_pk_join := (SELECT string_agg(format('a.%I = b.%I', c, c), ' AND ')
                    FROM unnest(v_pk_columns) AS c);

    -- Build non-PK equality check: a.col IS NOT DISTINCT FROM b.col AND ...
    IF array_length(v_non_pk_cols, 1) > 0 THEN
        v_non_pk_eq := (SELECT string_agg(
            format('a.%I IS NOT DISTINCT FROM b.%I', c, c), ' AND ')
            FROM unnest(v_non_pk_cols) AS c
        );
    ELSE
        v_non_pk_eq := 'TRUE';
    END IF;

    -- Iteratively merge adjacent identical records:
    -- Find a pair where a._valid_to = b._valid_from and all non-PK columns match,
    -- extend a to cover b's range, then delete b. Repeat until no pairs remain.
    LOOP
        EXECUTE format($q$
            WITH mergeable AS (
                SELECT a.ctid AS keep_ctid,
                       b.ctid AS drop_ctid,
                       b._valid_to AS extend_to
                  FROM %1$I.%2$I a
                  JOIN %1$I.%2$I b
                    ON %3$s
                   AND a._valid_to = b._valid_from
                   AND %4$s
                 LIMIT 1
            ),
            do_extend AS (
                UPDATE %1$I.%2$I h
                   SET _valid_to = m.extend_to
                  FROM mergeable m
                 WHERE h.ctid = m.keep_ctid
            )
            DELETE FROM %1$I.%2$I h
             USING mergeable m
             WHERE h.ctid = m.drop_ctid
        $q$, v_schema, v_history_table, v_pk_join, v_non_pk_eq);

        GET DIAGNOSTICS v_batch = ROW_COUNT;
        EXIT WHEN v_batch = 0;
        v_removed := v_removed + v_batch;
    END LOOP;

    RETURN v_removed;
END;
$$;
