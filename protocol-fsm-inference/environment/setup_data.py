#!/usr/bin/env python3
"""Generate synthetic protocol fuzzing data for the analysis task."""
import struct
import json
import os
import hashlib
import sqlite3

MAGIC = b'\x50\x46'
VERSION = 0x01

TRACE_CODES = [
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,4),(2,24),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,41),(1,2),(2,21),(1,3),(2,22),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,5),(2,25),(1,6),(2,30)],
    [(1,1),(2,50),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,4),(2,40),(1,3),(2,22),(1,4),(2,24),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,4),(2,24),(1,4),(2,24),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,4),(2,24),(1,5),(2,25),(1,6),(2,30)],
    [(1,1),(2,10),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,4),(2,50),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,41),(1,2),(2,41),(1,2),(2,21),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,4),(2,24),(1,3),(2,22),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,5),(2,25),(1,5),(2,25),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,41),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,4),(2,40),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,5),(2,50),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,5),(2,25),(1,4),(2,24),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,4),(2,24),(1,5),(2,25),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,4),(2,24),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,5),(2,25),(1,6),(2,30)],
    [(1,1),(2,10),(1,2),(2,21),(1,3),(2,22),(1,4),(2,24),(1,3),(2,22),
     (1,5),(2,25),(1,3),(2,22),(1,4),(2,24),(1,6),(2,30)],
]


def get_coverage_blocks(from_state, command):
    key = f"{from_state}_{command}"
    h = hashlib.sha256(key.encode()).hexdigest()
    n_blocks = 8 + (int(h[:2], 16) % 12)
    blocks = set()
    for i in range(min(n_blocks, len(h) // 3)):
        b = int(h[i * 3:(i + 1) * 3], 16) % 500
        blocks.add(b)
    return blocks


def encode_trace(codes, trace_id):
    msg_count = len(codes)
    data = MAGIC + struct.pack('BB', VERSION, msg_count)
    for idx, (direction, code) in enumerate(codes):
        payload = f"t{trace_id}m{idx}".encode()
        data += struct.pack('>BBH', direction, code, len(payload))
        data += payload
    return data


def get_trace_coverage(codes):
    blocks = set()
    state = 0
    i = 0
    while i < len(codes) - 1:
        if codes[i][0] == 1 and i + 1 < len(codes) and codes[i + 1][0] == 2:
            command = codes[i][1]
            blocks |= get_coverage_blocks(state, command)
            state = codes[i + 1][1]
            i += 2
        else:
            i += 1
    return blocks


def write_reference_dot(filepath, transitions, response_codes, commands):
    """Write reference FSM in Graphviz DOT format using human-readable names."""
    code_to_state = {int(k): v for k, v in response_codes.items()}
    code_to_state[0] = "INITIAL"
    code_to_cmd = {int(k): v for k, v in commands.items()}

    with open(filepath, 'w') as f:
        f.write("digraph reference_protocol {\n")
        f.write("    rankdir=LR;\n")
        f.write("    node [shape=circle, fontname=\"Helvetica\"];\n")
        f.write("    edge [fontname=\"Helvetica\"];\n\n")

        all_states = set()
        for t in transitions:
            all_states.add(t["from"])
            all_states.add(t["to"])

        for s in sorted(all_states):
            name = code_to_state.get(s, "S%d" % s)
            if s == 30:
                f.write("    %s [shape=doublecircle];\n" % name)
            else:
                f.write("    %s;\n" % name)

        f.write("\n")

        for t in transitions:
            src = code_to_state.get(t["from"], "S%d" % t["from"])
            dst = code_to_state.get(t["to"], "S%d" % t["to"])
            cmd = code_to_cmd.get(t["command"], "CMD%d" % t["command"])
            f.write("    %s -> %s [label=\"%s\"];\n" % (src, dst, cmd))

        f.write("}\n")


def main():
    os.makedirs('/app/traces', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    # Generate binary traces and compute coverage
    all_trace_coverage = {}
    for i, codes in enumerate(TRACE_CODES):
        name = "trace_%04d" % i
        data = encode_trace(codes, i)
        with open('/app/traces/%s.bin' % name, 'wb') as f:
            f.write(data)
        blocks = get_trace_coverage(codes)
        all_trace_coverage[name] = blocks

    # Write coverage data to SQLite database
    conn = sqlite3.connect('/app/coverage.db')
    conn.execute('''CREATE TABLE fuzzing_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    conn.execute("INSERT INTO fuzzing_meta VALUES ('campaign_name', 'SimpleFileTransfer-v1')")
    conn.execute("INSERT INTO fuzzing_meta VALUES ('fuzzer', 'aflnet')")
    conn.execute("INSERT INTO fuzzing_meta VALUES ('start_time', '2024-12-01T10:00:00Z')")
    conn.execute("INSERT INTO fuzzing_meta VALUES ('duration_sec', '3600')")
    conn.execute("INSERT INTO fuzzing_meta VALUES ('total_traces', '20')")

    conn.execute('''CREATE TABLE traces (
        trace_id INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_name TEXT UNIQUE NOT NULL,
        timestamp REAL NOT NULL,
        input_file TEXT NOT NULL,
        input_size INTEGER NOT NULL
    )''')

    conn.execute('''CREATE TABLE basic_block_coverage (
        trace_id INTEGER NOT NULL,
        block_id INTEGER NOT NULL,
        hit_count INTEGER DEFAULT 1,
        FOREIGN KEY (trace_id) REFERENCES traces(trace_id)
    )''')
    conn.execute('CREATE INDEX idx_bbc_trace ON basic_block_coverage(trace_id)')
    conn.execute('CREATE INDEX idx_bbc_block ON basic_block_coverage(block_id)')

    base_time = 1701424800.0
    for i, (name, blocks) in enumerate(sorted(all_trace_coverage.items())):
        trace_file = '/app/traces/%s.bin' % name
        file_size = os.path.getsize(trace_file)
        timestamp = base_time + i * 180.0
        conn.execute(
            'INSERT INTO traces (trace_name, timestamp, input_file, input_size) VALUES (?, ?, ?, ?)',
            (name, timestamp, '%s.bin' % name, file_size)
        )
        trace_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        for block in sorted(blocks):
            hit_count = 1 + ((block * 31 + len(name)) % 5)
            conn.execute(
                'INSERT INTO basic_block_coverage (trace_id, block_id, hit_count) VALUES (?, ?, ?)',
                (trace_id, block, hit_count)
            )

    conn.commit()
    conn.close()

    # Write protocol spec
    spec = {
        "name": "SimpleFileTransfer Protocol v1",
        "trace_format": {
            "header": {
                "magic": [80, 70],
                "version": {"offset": 2, "type": "uint8"},
                "message_count": {"offset": 3, "type": "uint8"}
            },
            "header_size": 4,
            "message": {
                "direction": {"offset": 0, "type": "uint8",
                              "values": {"1": "request", "2": "response"}},
                "code": {"offset": 1, "type": "uint8"},
                "payload_length": {"offset": 2, "type": "uint16_be"},
                "payload": {"offset": 4, "type": "bytes"}
            },
            "message_header_size": 4
        },
        "commands": {
            "1": "CONNECT", "2": "AUTH", "3": "LIST",
            "4": "RETR", "5": "STOR", "6": "QUIT"
        },
        "response_codes": {
            "10": "CONNECTION_OK", "21": "AUTH_OK", "22": "LIST_OK",
            "24": "TRANSFER_READ_OK", "25": "TRANSFER_WRITE_OK", "30": "BYE",
            "40": "BAD_REQUEST", "41": "AUTH_FAIL", "50": "ERROR"
        },
        "initial_state": 0,
        "state_definition": "States are identified by the most recent server response code. The initial state before any response is 0.",
        "coverage_format": {
            "storage": "sqlite3",
            "database": "/app/coverage.db",
            "description": "Coverage data stored in SQLite database with tables: fuzzing_meta, traces, basic_block_coverage"
        }
    }
    with open('/app/protocol_spec.json', 'w') as f:
        json.dump(spec, f, indent=2)

    # Write reference FSM in DOT format
    reference_transitions = [
        {"from": 0, "command": 1, "to": 10},
        {"from": 0, "command": 1, "to": 50},
        {"from": 10, "command": 2, "to": 21},
        {"from": 10, "command": 2, "to": 41},
        {"from": 10, "command": 6, "to": 30},
        {"from": 21, "command": 3, "to": 22},
        {"from": 21, "command": 4, "to": 40},
        {"from": 21, "command": 5, "to": 40},
        {"from": 21, "command": 6, "to": 30},
        {"from": 22, "command": 3, "to": 22},
        {"from": 22, "command": 4, "to": 24},
        {"from": 22, "command": 4, "to": 50},
        {"from": 22, "command": 5, "to": 25},
        {"from": 22, "command": 5, "to": 50},
        {"from": 22, "command": 6, "to": 30},
        {"from": 24, "command": 3, "to": 22},
        {"from": 24, "command": 4, "to": 24},
        {"from": 24, "command": 5, "to": 25},
        {"from": 24, "command": 6, "to": 30},
        {"from": 25, "command": 3, "to": 22},
        {"from": 25, "command": 4, "to": 24},
        {"from": 25, "command": 5, "to": 25},
        {"from": 25, "command": 6, "to": 30},
        {"from": 40, "command": 2, "to": 21},
        {"from": 40, "command": 3, "to": 22},
        {"from": 40, "command": 6, "to": 30},
        {"from": 41, "command": 2, "to": 21},
        {"from": 41, "command": 2, "to": 41},
        {"from": 41, "command": 6, "to": 30},
        {"from": 50, "command": 6, "to": 30}
    ]
    write_reference_dot('/app/reference.dot', reference_transitions,
                        spec["response_codes"], spec["commands"])


if __name__ == '__main__':
    main()
