#!/usr/bin/env python3
"""Build reference SQLite database and NDJSON event logs from replay trace files.

This script converts the JSON replay traces into two queryable formats:
1. A SQLite database (/app/reference.db) for structured queries
2. NDJSON event logs (/app/logs/server.ndjson) for jq-based filtering
"""
import json
import sqlite3
import os
import glob

os.makedirs('/app/logs', exist_ok=True)

db = sqlite3.connect('/app/reference.db')

db.execute('''CREATE TABLE trace_meta (
    trace TEXT PRIMARY KEY,
    description TEXT,
    config_json TEXT,
    initial_state_json TEXT
)''')

db.execute('''CREATE TABLE action_results (
    trace TEXT NOT NULL,
    step INTEGER NOT NULL,
    agent TEXT NOT NULL,
    action_type TEXT NOT NULL,
    params TEXT,
    expected_result TEXT NOT NULL,
    comment TEXT
)''')

db.execute('''CREATE TABLE agent_states (
    trace TEXT NOT NULL,
    step INTEGER NOT NULL,
    agent TEXT NOT NULL,
    x INTEGER,
    y INTEGER,
    energy INTEGER,
    deactivated INTEGER,
    deactivated_steps INTEGER,
    comment TEXT
)''')

db.execute('''CREATE TABLE block_states (
    trace TEXT NOT NULL,
    step INTEGER NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    type TEXT NOT NULL
)''')

db.execute('''CREATE TABLE score_states (
    trace TEXT NOT NULL,
    step INTEGER NOT NULL,
    team TEXT NOT NULL,
    score INTEGER NOT NULL
)''')

db.execute('CREATE INDEX idx_ar_trace_step ON action_results(trace, step)')
db.execute('CREATE INDEX idx_as_trace_step ON agent_states(trace, step)')
db.execute('CREATE INDEX idx_ar_action ON action_results(action_type)')
db.execute('CREATE INDEX idx_bs_trace ON block_states(trace, step)')

ndjson_lines = []

for replay_file in sorted(glob.glob('/app/replays/replay_*.json')):
    trace_name = os.path.basename(replay_file).replace('replay_', '').replace('.json', '')

    with open(replay_file) as f:
        replay = json.load(f)

    config = replay['config']
    initial_state = replay['initial_state']
    description = replay.get('description', replay.get('name', trace_name))

    db.execute('INSERT INTO trace_meta VALUES (?, ?, ?, ?)',
               (trace_name, description, json.dumps(config), json.dumps(initial_state)))

    for step_data in replay['trace']:
        step_num = step_data['step']
        actions = step_data.get('actions', {})
        expected = step_data.get('expected', {})
        comment = step_data.get('comment', '')

        for agent, result in expected.get('results', {}).items():
            action = actions.get(agent, {'type': 'skip', 'p': []})
            atype = action.get('type', 'skip')
            params = json.dumps(action.get('p', []))
            db.execute('INSERT INTO action_results VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (trace_name, step_num, agent, atype, params, result, comment))
            ndjson_lines.append(json.dumps({
                'trace': trace_name, 'step': step_num, 'event': 'action_result',
                'agent': agent, 'action': atype, 'params': json.loads(params),
                'result': result, 'comment': comment
            }, separators=(',', ':')))

        for agent, state in expected.get('agents', {}).items():
            db.execute('INSERT INTO agent_states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       (trace_name, step_num, agent,
                        state.get('x'), state.get('y'),
                        state.get('energy'),
                        1 if state.get('deactivated') else (0 if 'deactivated' in state else None),
                        state.get('deactivated_steps'),
                        comment))
            event = {'trace': trace_name, 'step': step_num, 'event': 'state_update',
                     'agent': agent, 'comment': comment}
            event.update(state)
            ndjson_lines.append(json.dumps(event, separators=(',', ':')))

        for block in expected.get('blocks', []):
            db.execute('INSERT INTO block_states VALUES (?, ?, ?, ?, ?)',
                       (trace_name, step_num, block['x'], block['y'], block['type']))
            ndjson_lines.append(json.dumps({
                'trace': trace_name, 'step': step_num, 'event': 'block_update',
                'x': block['x'], 'y': block['y'], 'type': block['type']
            }, separators=(',', ':')))

        for team, score in expected.get('scores', {}).items():
            db.execute('INSERT INTO score_states VALUES (?, ?, ?, ?)',
                       (trace_name, step_num, team, score))
            ndjson_lines.append(json.dumps({
                'trace': trace_name, 'step': step_num, 'event': 'score_update',
                'team': team, 'score': score
            }, separators=(',', ':')))

db.commit()
db.close()

with open('/app/logs/server.ndjson', 'w') as f:
    f.write('\n'.join(ndjson_lines) + '\n')

print(f"Built reference.db ({len(ndjson_lines)} events from "
      f"{len(glob.glob('/app/replays/replay_*.json'))} traces)")
