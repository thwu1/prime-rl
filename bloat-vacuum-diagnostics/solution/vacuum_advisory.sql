-- Vacuum advisory function: recommends maintenance actions based on bloat estimates

CREATE OR REPLACE FUNCTION vacuum_advisory(p_schema TEXT DEFAULT 'public')
RETURNS TABLE (
    table_name TEXT,
    table_size_bytes BIGINT,
    estimated_bloat_pct DOUBLE PRECISION,
    dead_tuple_count BIGINT,
    dead_tuple_pct DOUBLE PRECISION,
    max_index_bloat_pct DOUBLE PRECISION,
    last_vacuum TIMESTAMPTZ,
    last_autovacuum TIMESTAMPTZ,
    recommendation TEXT
) AS $$
BEGIN
    RETURN QUERY
    WITH table_bloat AS (
        SELECT
            s3.schemaname, s3.tblname,
            s3.bs * s3.tblpages AS real_size,
            CASE WHEN s3.tblpages > 0 AND s3.tblpages - s3.est_tblpages_ff > 0
                THEN 100.0 * (s3.tblpages - s3.est_tblpages_ff) / s3.tblpages
                ELSE 0
            END AS bloat_pct
        FROM (
            SELECT
                ceil(s2.reltuples / ((s2.bs - s2.page_hdr) / s2.tpl_size)) + ceil(s2.toasttuples / 4) AS est_tblpages,
                ceil(s2.reltuples / ((s2.bs - s2.page_hdr) * s2.fillfactor / (s2.tpl_size * 100))) + ceil(s2.toasttuples / 4) AS est_tblpages_ff,
                s2.tblpages, s2.fillfactor, s2.bs, s2.schemaname, s2.tblname
            FROM (
                SELECT
                    (4 + s1.tpl_hdr_size + s1.tpl_data_size + (2 * s1.ma)
                        - CASE WHEN s1.tpl_hdr_size % s1.ma = 0 THEN s1.ma ELSE s1.tpl_hdr_size % s1.ma END
                        - CASE WHEN ceil(s1.tpl_data_size)::int % s1.ma = 0 THEN s1.ma ELSE ceil(s1.tpl_data_size)::int % s1.ma END
                    ) AS tpl_size,
                    (s1.heappages + s1.toastpages) AS tblpages,
                    s1.reltuples, s1.toasttuples, s1.bs, s1.page_hdr,
                    s1.schemaname, s1.tblname, s1.fillfactor, s1.ma
                FROM (
                    SELECT
                        tbl.reltuples,
                        tbl.relpages AS heappages,
                        coalesce(toast.relpages, 0) AS toastpages,
                        coalesce(toast.reltuples, 0) AS toasttuples,
                        coalesce(substring(
                            array_to_string(tbl.reloptions, ' ')
                            FROM 'fillfactor=([0-9]+)')::smallint, 100) AS fillfactor,
                        current_setting('block_size')::numeric AS bs,
                        CASE WHEN version() ~ 'mingw32' OR version() ~ '64-bit|x86_64|ppc64|ia64|amd64' THEN 8 ELSE 4 END AS ma,
                        24 AS page_hdr,
                        23 + CASE WHEN MAX(coalesce(s.null_frac, 0)) > 0 THEN (7 + count(s.attname)) / 8 ELSE 0::int END
                            + CASE WHEN bool_or(att.attname = 'oid' AND att.attnum < 0) THEN 4 ELSE 0 END AS tpl_hdr_size,
                        sum((1 - coalesce(s.null_frac, 0)) * coalesce(s.avg_width, 0)) AS tpl_data_size,
                        ns.nspname AS schemaname,
                        tbl.relname AS tblname
                    FROM pg_attribute AS att
                        JOIN pg_class AS tbl ON att.attrelid = tbl.oid
                        JOIN pg_namespace AS ns ON ns.oid = tbl.relnamespace
                        LEFT JOIN pg_stats AS s ON s.schemaname = ns.nspname
                            AND s.tablename = tbl.relname AND s.inherited = false AND s.attname = att.attname
                        LEFT JOIN pg_class AS toast ON tbl.reltoastrelid = toast.oid
                    WHERE NOT att.attisdropped
                        AND tbl.relkind IN ('r', 'm')
                        AND ns.nspname = p_schema
                    GROUP BY tbl.oid, ns.nspname, tbl.relname, tbl.reltuples, tbl.relpages,
                        toast.relpages, toast.reltuples, tbl.reloptions
                ) AS s1
            ) AS s2
            WHERE s2.tblpages > 0
        ) AS s3
    ),
    index_bloat AS (
        SELECT
            rs.tblname,
            rs.idxname,
            CASE WHEN rs.relpages > rs.est_pages_ff
                THEN 100.0 * (rs.relpages - rs.est_pages_ff) / rs.relpages
                ELSE 0
            END AS idx_bloat_pct
        FROM (
            SELECT
                coalesce(1 + ceil(hp.reltuples / floor((hp.bs - hp.pageopqdata - hp.pagehdr) / (4 + hp.nulldatahdrwidth)::float)), 0) AS est_pages,
                coalesce(1 + ceil(hp.reltuples / floor((hp.bs - hp.pageopqdata - hp.pagehdr) * hp.fillfactor / (100 * (4 + hp.nulldatahdrwidth)::float))), 0) AS est_pages_ff,
                hp.tblname, hp.idxname, hp.relpages, hp.fillfactor
            FROM (
                SELECT rd.maxalign, rd.bs, rd.tblname, rd.idxname, rd.reltuples, rd.relpages, rd.fillfactor,
                    (rd.index_tuple_hdr_bm +
                        rd.maxalign - CASE WHEN rd.index_tuple_hdr_bm % rd.maxalign = 0 THEN rd.maxalign ELSE rd.index_tuple_hdr_bm % rd.maxalign END
                        + rd.nulldatawidth + rd.maxalign - CASE
                            WHEN rd.nulldatawidth = 0 THEN 0
                            WHEN rd.nulldatawidth::integer % rd.maxalign = 0 THEN rd.maxalign
                            ELSE rd.nulldatawidth::integer % rd.maxalign
                        END
                    )::numeric AS nulldatahdrwidth, rd.pagehdr, rd.pageopqdata
                FROM (
                    SELECT n.nspname, i.tblname, i.idxname, i.reltuples, i.relpages,
                        i.fillfactor, current_setting('block_size')::numeric AS bs,
                        CASE WHEN version() ~ 'mingw32' OR version() ~ '64-bit|x86_64|ppc64|ia64|amd64' THEN 8 ELSE 4 END AS maxalign,
                        24 AS pagehdr,
                        16 AS pageopqdata,
                        CASE WHEN max(coalesce(s.null_frac, 0)) = 0
                            THEN 8
                            ELSE 8 + ((32 + 8 - 1) / 8)
                        END AS index_tuple_hdr_bm,
                        sum((1 - coalesce(s.null_frac, 0)) * coalesce(s.avg_width, 1024)) AS nulldatawidth
                    FROM (
                        SELECT ct.relname AS tblname, ct.relnamespace, ic.idxname, ic.attpos, ic.indkey,
                            ic.reltuples, ic.relpages, ic.tbloid, ic.idxoid, ic.fillfactor,
                            coalesce(a1.attnum, a2.attnum) AS attnum,
                            coalesce(a1.attname, a2.attname) AS attname,
                            coalesce(a1.atttypid, a2.atttypid) AS atttypid,
                            CASE WHEN a1.attnum IS NULL THEN ic.idxname ELSE ct.relname END AS attrelname
                        FROM (
                            SELECT idxname, reltuples, relpages, tbloid, idxoid, fillfactor, indkey,
                                pg_catalog.generate_series(1, indnatts) AS attpos
                            FROM (
                                SELECT ci.relname AS idxname, ci.reltuples, ci.relpages, idx.indrelid AS tbloid,
                                    idx.indexrelid AS idxoid,
                                    coalesce(substring(array_to_string(ci.reloptions, ' ') FROM 'fillfactor=([0-9]+)')::smallint, 90) AS fillfactor,
                                    idx.indnatts,
                                    pg_catalog.string_to_array(pg_catalog.textin(pg_catalog.int2vectorout(idx.indkey)), ' ')::int[] AS indkey
                                FROM pg_catalog.pg_index idx
                                JOIN pg_catalog.pg_class ci ON ci.oid = idx.indexrelid
                                WHERE ci.relam = (SELECT oid FROM pg_am WHERE amname = 'btree')
                                    AND ci.relpages > 0
                            ) AS idx_data
                        ) AS ic
                        JOIN pg_catalog.pg_class ct ON ct.oid = ic.tbloid
                        LEFT JOIN pg_catalog.pg_attribute a1 ON ic.indkey[ic.attpos] <> 0 AND a1.attrelid = ic.tbloid AND a1.attnum = ic.indkey[ic.attpos]
                        LEFT JOIN pg_catalog.pg_attribute a2 ON ic.indkey[ic.attpos] = 0 AND a2.attrelid = ic.idxoid AND a2.attnum = ic.attpos
                    ) i
                    JOIN pg_catalog.pg_namespace n ON n.oid = i.relnamespace
                    JOIN pg_catalog.pg_stats s ON s.schemaname = n.nspname AND s.tablename = i.attrelname AND s.attname = i.attname
                    WHERE n.nspname = p_schema
                    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
                ) AS rd
            ) AS hp
        ) AS rs
        WHERE rs.relpages > 0
    ),
    max_idx_bloat AS (
        SELECT ib.tblname, COALESCE(max(ib.idx_bloat_pct), 0) AS max_ibp
        FROM index_bloat ib
        GROUP BY ib.tblname
    ),
    dead_stats AS (
        SELECT
            st.relname,
            st.n_dead_tup,
            CASE WHEN st.n_live_tup + st.n_dead_tup > 0
                THEN 100.0 * st.n_dead_tup / (st.n_live_tup + st.n_dead_tup)
                ELSE 0
            END AS dead_pct,
            st.last_vacuum,
            st.last_autovacuum
        FROM pg_stat_user_tables st
        WHERE st.schemaname = p_schema
    )
    SELECT
        tb.tblname::TEXT,
        (tb.real_size)::BIGINT,
        (tb.bloat_pct)::DOUBLE PRECISION,
        COALESCE(ds.n_dead_tup, 0)::BIGINT,
        COALESCE(ds.dead_pct, 0)::DOUBLE PRECISION,
        COALESCE(mib.max_ibp, 0)::DOUBLE PRECISION,
        ds.last_vacuum,
        ds.last_autovacuum,
        CASE
            WHEN tb.bloat_pct > 50 THEN 'VACUUM FULL'
            WHEN COALESCE(mib.max_ibp, 0) > 30 AND tb.bloat_pct <= 50 THEN 'REINDEX'
            WHEN tb.bloat_pct > 20 OR COALESCE(ds.dead_pct, 0) > 5 THEN 'VACUUM'
            ELSE 'OK'
        END::TEXT
    FROM table_bloat tb
    LEFT JOIN dead_stats ds ON ds.relname = tb.tblname
    LEFT JOIN max_idx_bloat mib ON mib.tblname = tb.tblname
    ORDER BY tb.tblname;
END;
$$ LANGUAGE plpgsql;
