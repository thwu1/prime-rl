-- SQLite schema for analyzing JSONL simulation traces
--
-- Usage:
--   sqlite3 /opt/llm-sim/traces/analysis.db < /opt/llm-sim/trace_schema.sql
--
-- Then load a trace:
--   python3 -c "
--   import json, sys, sqlite3
--   conn = sqlite3.connect('/opt/llm-sim/traces/analysis.db')
--   for line in open('/opt/llm-sim/traces/baseline.jsonl'):
--       e = json.loads(line)
--       conn.execute('INSERT INTO events VALUES (?,?,?)',
--                    (e.get('ts'), e.get('event'), json.dumps(e)))
--   conn.commit()
--   "

CREATE TABLE IF NOT EXISTS events (
    ts          REAL,
    event_type  TEXT,
    data        TEXT     -- Full JSON event payload
);

CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_event_ts   ON events(ts);

-- Convenience view: completed requests
CREATE VIEW IF NOT EXISTS completions AS
SELECT
    ts,
    json_extract(data, '$.req_id')     AS req_id,
    json_extract(data, '$.jct')        AS jct,
    json_extract(data, '$.slo_tier')   AS slo_tier,
    json_extract(data, '$.slo_met')    AS slo_met,
    json_extract(data, '$.slo_deadline') AS slo_deadline,
    json_extract(data, '$.preemptions') AS preemptions
FROM events WHERE event_type = 'complete';

-- Convenience view: scheduling decisions
CREATE VIEW IF NOT EXISTS schedules AS
SELECT
    ts,
    json_extract(data, '$.req_id')       AS req_id,
    json_extract(data, '$.pages')        AS pages,
    json_extract(data, '$.gpu_util')     AS gpu_util,
    json_extract(data, '$.frag')         AS frag,
    json_extract(data, '$.load_cost_ms') AS load_cost_ms
FROM events WHERE event_type = 'schedule';

-- Convenience view: arrivals
CREATE VIEW IF NOT EXISTS arrivals AS
SELECT
    ts,
    json_extract(data, '$.req_id')       AS req_id,
    json_extract(data, '$.input_tokens') AS input_tokens,
    json_extract(data, '$.output_tokens') AS output_tokens,
    json_extract(data, '$.slo_tier')     AS slo_tier
FROM events WHERE event_type = 'arrival';
