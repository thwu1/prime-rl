--
-- Extract all evaluation data from the normalized SQLite schema as a single
-- JSON document with keys: models, tasks, evaluations.
-- Pivots pricing rows into dicts, groups runs into evaluations, converts
-- SQLite integer booleans to JSON booleans.

.headers off
.mode list

SELECT json_object(
    'models', (
        SELECT json_group_array(
            json_object(
                'model_id', m.model_id,
                'release_date', m.release_date,
                'training_cutoff', m.training_cutoff,
                'pricing', json(
                    (SELECT json_group_object(
                        CASE p.tier
                            WHEN 'input' THEN 'input_per_mtok'
                            WHEN 'cached_input' THEN 'cached_input_per_mtok'
                            WHEN 'output' THEN 'output_per_mtok'
                        END,
                        p.price_per_mtok
                    )
                    FROM pricing p
                    WHERE p.model_id = m.model_id)
                )
            )
        )
        FROM models m
    ),
    'tasks', (
        SELECT json_group_array(
            json_object(
                'task_id', t.task_id,
                'repo', t.repo,
                'created_at', t.created_at
            )
        )
        FROM tasks t
    ),
    'evaluations', (
        SELECT json_group_array(json(eval_json))
        FROM (
            SELECT json_object(
                'model_id', r.model_id,
                'task_id', r.task_id,
                'runs', json_group_array(
                    json_object(
                        'run_id', r.run_id,
                        'resolved', json(CASE WHEN r.resolved = 1 THEN 'true' ELSE 'false' END),
                        'input_tokens', r.input_tokens,
                        'cached_tokens', r.cached_tokens,
                        'output_tokens', r.output_tokens
                    )
                )
            ) AS eval_json
            FROM runs r
            GROUP BY r.model_id, r.task_id
        )
    )
);
