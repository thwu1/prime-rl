-- Generate rankings JSON from metrics table
-- Produces a JSON array of ranked submissions

SELECT json_group_array(
    json_object(
        'rank', row_number() OVER (ORDER BY composite_score ASC),
        'name', file_stem,
        'team', team,
        'eval_set', eval_set,
        'composite_score', composite_score,
        'auc_roc', auc_roc,
        'brier_score', brier_score,
        'ece', ece
    )
)
FROM metrics;
