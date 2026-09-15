-- Extract scenario configurations from calibration database
-- Outputs JSON array of scenario objects for the analysis pipeline
.headers off
SELECT json_group_array(
    json_object(
        'id', id,
        'noise_type', noise_type,
        'ideal_value', ideal_value,
        'decay_rate', decay_rate,
        'asymptote', COALESCE(asymptote, 0.0),
        'poly_coefficients', CASE
            WHEN noise_type = 'polynomial' THEN json(poly_coefficients)
            ELSE json('null')
        END,
        'scale_factors', json(scale_factors),
        'shot_budget', shot_budget
    )
) FROM scenarios ORDER BY id;
