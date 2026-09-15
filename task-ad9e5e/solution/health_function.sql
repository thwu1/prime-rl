
CREATE EXTENSION IF NOT EXISTS pgstattuple;

CREATE OR REPLACE FUNCTION public.vacuum_health_report()
RETURNS TABLE (
    check_name TEXT,
    status TEXT,
    current_value TEXT,
    recommended_action TEXT
) AS $$
DECLARE
    _count INT;
    _val TEXT;
    _num FLOAT;
    _mem_mb FLOAT;
    _rec RECORD;
    _dead_pct FLOAT;
    _sf_val TEXT;
    _has_disabled BOOLEAN := FALSE;
BEGIN
    -- Check: Orphaned prepared transactions
    SELECT COUNT(*) INTO _count FROM pg_prepared_xacts;
    check_name := 'prepared_transactions';
    current_value := _count::TEXT;
    IF _count > 0 THEN
        status := 'CRITICAL';
        recommended_action := 'ROLLBACK PREPARED orphaned transactions to unblock xmin horizon';
    ELSE
        status := 'OK';
        recommended_action := 'No action needed';
    END IF;
    RETURN NEXT;

    -- Check: Tables with autovacuum explicitly disabled
    FOR _rec IN
        SELECT c.relname::TEXT AS tname
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND c.reloptions IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM unnest(c.reloptions) opt
              WHERE opt ILIKE 'autovacuum_enabled=false'
          )
    LOOP
        check_name := 'autovacuum_disabled_' || _rec.tname;
        status := 'CRITICAL';
        current_value := 'autovacuum_enabled=false';
        recommended_action := 'ALTER TABLE ' || _rec.tname || ' SET (autovacuum_enabled = true)';
        RETURN NEXT;
        _has_disabled := TRUE;
    END LOOP;
    IF NOT _has_disabled THEN
        check_name := 'autovacuum_enabled_all';
        status := 'OK';
        current_value := 'All tables have autovacuum enabled';
        recommended_action := 'No action needed';
        RETURN NEXT;
    END IF;

    -- Check: Per-table autovacuum_vacuum_scale_factor
    FOR _rec IN
        SELECT c.relname::TEXT AS tname
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND c.relname IN ('orders', 'order_items', 'audit_log')
        ORDER BY c.relname
    LOOP
        SELECT option_value INTO _sf_val
        FROM pg_options_to_table(
            (SELECT reloptions FROM pg_class WHERE relname = _rec.tname)
        )
        WHERE option_name = 'autovacuum_vacuum_scale_factor';

        check_name := 'scale_factor_' || _rec.tname;
        IF _sf_val IS NULL THEN
            status := 'WARNING';
            current_value := 'default (0.2)';
            recommended_action := 'Set autovacuum_vacuum_scale_factor < 0.05';
        ELSIF _sf_val::FLOAT >= 0.05 THEN
            status := 'WARNING';
            current_value := _sf_val;
            recommended_action := 'Reduce autovacuum_vacuum_scale_factor below 0.05';
        ELSE
            status := 'OK';
            current_value := _sf_val;
            recommended_action := 'No action needed';
        END IF;
        RETURN NEXT;
    END LOOP;

    -- Check: autovacuum_vacuum_cost_delay
    SHOW autovacuum_vacuum_cost_delay INTO _val;
    _num := regexp_replace(_val, '[^0-9.]', '', 'g')::FLOAT;
    check_name := 'cost_delay';
    current_value := _val;
    IF _num > 5 THEN
        status := 'CRITICAL';
        recommended_action := 'Reduce autovacuum_vacuum_cost_delay to 5ms or less';
    ELSE
        status := 'OK';
        recommended_action := 'No action needed';
    END IF;
    RETURN NEXT;

    -- Check: autovacuum_vacuum_cost_limit
    SHOW autovacuum_vacuum_cost_limit INTO _val;
    _num := _val::FLOAT;
    check_name := 'cost_limit';
    current_value := _val;
    IF _num < 200 THEN
        status := 'CRITICAL';
        recommended_action := 'Increase autovacuum_vacuum_cost_limit to 200 or greater';
    ELSE
        status := 'OK';
        recommended_action := 'No action needed';
    END IF;
    RETURN NEXT;

    -- Check: maintenance_work_mem
    SHOW maintenance_work_mem INTO _val;
    IF _val LIKE '%GB%' THEN
        _mem_mb := regexp_replace(_val, '[^0-9.]', '', 'g')::FLOAT * 1024;
    ELSIF _val LIKE '%MB%' THEN
        _mem_mb := regexp_replace(_val, '[^0-9.]', '', 'g')::FLOAT;
    ELSIF _val LIKE '%kB%' THEN
        _mem_mb := regexp_replace(_val, '[^0-9.]', '', 'g')::FLOAT / 1024;
    ELSE
        _mem_mb := _val::FLOAT / (1024 * 1024);
    END IF;
    check_name := 'maintenance_work_mem';
    current_value := _val;
    IF _mem_mb < 256 THEN
        status := 'CRITICAL';
        recommended_action := 'Increase maintenance_work_mem to 256MB or greater';
    ELSE
        status := 'OK';
        recommended_action := 'No action needed';
    END IF;
    RETURN NEXT;

    -- Check: idle_in_transaction_session_timeout
    SHOW idle_in_transaction_session_timeout INTO _val;
    check_name := 'idle_in_transaction_timeout';
    current_value := _val;
    IF _val = '0' THEN
        status := 'CRITICAL';
        recommended_action := 'Set idle_in_transaction_session_timeout to prevent vacuum-blocking idle transactions';
    ELSE
        status := 'OK';
        recommended_action := 'No action needed';
    END IF;
    RETURN NEXT;

    -- Check: Dead tuple bloat per table
    FOR _rec IN
        SELECT c.relname::TEXT AS tname
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND c.relname IN ('orders', 'order_items', 'audit_log')
        ORDER BY c.relname
    LOOP
        SELECT dead_tuple_percent INTO _dead_pct
        FROM pgstattuple(_rec.tname);

        check_name := 'dead_tuples_' || _rec.tname;
        current_value := round(_dead_pct::NUMERIC, 2)::TEXT || '%';
        IF _dead_pct >= 10 THEN
            status := 'CRITICAL';
            recommended_action := 'Run VACUUM on ' || _rec.tname;
        ELSIF _dead_pct >= 5 THEN
            status := 'WARNING';
            recommended_action := 'Consider running VACUUM on ' || _rec.tname;
        ELSE
            status := 'OK';
            recommended_action := 'No action needed';
        END IF;
        RETURN NEXT;
    END LOOP;
END;
$$ LANGUAGE plpgsql;
