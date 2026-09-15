
-- Retention delete function: deletes events older than p_cutoff in batches.
-- Uses the idx_retention_created index (created_at ASC) for efficient scanning.
-- The inner SELECT finds the oldest p_batch_size events before the cutoff via
-- an ordered index scan, then the outer DELETE removes them by PK lookup.
-- Loops until no more rows match.

CREATE OR REPLACE FUNCTION app.delete_old_events(
    p_cutoff TIMESTAMPTZ,
    p_batch_size INT DEFAULT 1000
) RETURNS BIGINT
LANGUAGE plpgsql AS $$
DECLARE
    v_total BIGINT := 0;
    v_batch BIGINT;
BEGIN
    LOOP
        DELETE FROM app.events
        WHERE id IN (
            SELECT id
            FROM app.events
            WHERE created_at < p_cutoff
            ORDER BY created_at ASC
            LIMIT p_batch_size
        );

        GET DIAGNOSTICS v_batch = ROW_COUNT;
        v_total := v_total + v_batch;
        EXIT WHEN v_batch = 0;
    END LOOP;

    RETURN v_total;
END;
$$;
