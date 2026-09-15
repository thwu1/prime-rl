
INSERT INTO app.events (tenant_id, event_type, severity, created_at, resolved_at, status, source_system, description, assigned_to)
WITH base AS (
    SELECT
        gs,
        random() AS r_tenant,
        random() AS r_type,
        random() AS r_sev,
        '2024-01-01 00:00:00+00'::timestamptz + (random() * interval '181 days') AS ts,
        random() AS r_status,
        random() AS r_source,
        random() AS r_assign,
        random() AS r_resolve
    FROM generate_series(1, 500000) AS gs
),
with_status AS (
    SELECT
        gs, r_tenant, r_type, r_sev, ts, r_status, r_source, r_assign, r_resolve,
        CASE
            WHEN r_status < 0.45 THEN 'RESOLVED'
            WHEN r_status < 0.55 THEN 'CLOSED'
            WHEN r_status < 0.70 THEN 'OPEN'
            WHEN r_status < 0.85 THEN 'ACKNOWLEDGED'
            ELSE 'IN_PROGRESS'
        END AS status_val
    FROM base
)
SELECT
    (ARRAY[
        'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
        'b1ffbc99-9c0b-4ef8-bb6d-6bb9bd380a22',
        'c2ffbc99-9c0b-4ef8-bb6d-6bb9bd380a33',
        'd3ffbc99-9c0b-4ef8-bb6d-6bb9bd380a44',
        'e4ffbc99-9c0b-4ef8-bb6d-6bb9bd380a55',
        'f5ffbc99-9c0b-4ef8-bb6d-6bb9bd380a66',
        '06ffbc99-9c0b-4ef8-bb6d-6bb9bd380a77',
        '17ffbc99-9c0b-4ef8-bb6d-6bb9bd380a88',
        '28ffbc99-9c0b-4ef8-bb6d-6bb9bd380a99',
        '39ffbc99-9c0b-4ef8-bb6d-6bb9bd380aaa'
    ]::uuid[])[floor(r_tenant * 10)::int + 1] AS tenant_id,
    (ARRAY['ALERT', 'INCIDENT', 'CHANGE', 'MAINTENANCE', 'DEPLOYMENT'])[floor(r_type * 5)::int + 1] AS event_type,
    CASE
        WHEN r_sev < 0.35 THEN 1
        WHEN r_sev < 0.60 THEN 2
        WHEN r_sev < 0.80 THEN 3
        WHEN r_sev < 0.93 THEN 4
        ELSE 5
    END AS severity,
    ts AS created_at,
    CASE
        WHEN status_val IN ('RESOLVED', 'CLOSED')
        THEN ts + (r_resolve * interval '72 hours')
        ELSE NULL
    END AS resolved_at,
    status_val AS status,
    (ARRAY['prometheus', 'grafana', 'datadog', 'pagerduty', 'cloudwatch', 'nagios', 'splunk'])[floor(r_source * 7)::int + 1] AS source_system,
    'Event ' || gs::text AS description,
    CASE
        WHEN r_assign < 0.7
        THEN (ARRAY[
            '11111111-1111-1111-1111-111111111111',
            '22222222-2222-2222-2222-222222222222',
            '33333333-3333-3333-3333-333333333333',
            '44444444-4444-4444-4444-444444444444',
            '55555555-5555-5555-5555-555555555555'
        ]::uuid[])[floor((r_assign / 0.7) * 5)::int + 1]
        ELSE NULL
    END AS assigned_to
FROM with_status;
