--
-- Audit query: join category metrics with overall metrics for a full report.
-- Run: sqlite3 -header -csv /app/benchmark.db < /app/audit_query.sql

SELECT
    cm.tool_name,
    cm.category,
    cm.tp,
    cm.fn,
    cm.fp,
    cm.tn,
    ROUND(cm.tpr, 4) AS tpr,
    ROUND(cm.fpr, 4) AS fpr,
    ROUND(om.macro_tpr, 4) AS macro_tpr,
    ROUND(om.macro_fpr, 4) AS macro_fpr,
    ROUND(om.youdens_j, 4) AS youdens_j
FROM category_metrics cm
JOIN overall_metrics om ON cm.tool_name = om.tool_name
ORDER BY om.youdens_j DESC, cm.tool_name ASC, cm.category ASC;
