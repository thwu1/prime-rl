#!/usr/bin/env python3
"""Generate synthetic LLM serving benchmark data in SQLite and config in YAML."""
import json
import random
import os
import sqlite3

random.seed(42)

REQUEST_RATES = [1.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
NUM_REQUESTS = 500
BASE_SERVICE_RATE = 22.0
MEM_FRACTION_STATIC = 0.88

os.makedirs('/app/data/server_logs', exist_ok=True)

# --- SQLite database for benchmark traces ---
db_path = '/app/data/benchmarks.db'
if os.path.exists(db_path):
    os.remove(db_path)
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute('''CREATE TABLE runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_rate REAL NOT NULL,
    num_requests INTEGER NOT NULL
)''')

cur.execute('''CREATE TABLE traces (
    run_id INTEGER NOT NULL,
    request_id INTEGER NOT NULL,
    arrival_time REAL NOT NULL,
    prompt_len INTEGER NOT NULL,
    output_len INTEGER NOT NULL,
    ttft REAL NOT NULL,
    latency REAL NOT NULL,
    success INTEGER NOT NULL DEFAULT 1,
    itl TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (run_id, request_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
)''')

# --- Server startup log (no mem_fraction_static here) ---
startup_lines = [
    "[2025-01-15 09:58:30] Launching SGLang server...",
    "[2025-01-15 09:58:31] Loading model weights for MoE-47B (tp_size=2)...",
    "[2025-01-15 09:59:45] Model loaded successfully.",
    "[2025-01-15 09:59:46] Memory pool initialized: max_total_num_tokens=524288",
    "[2025-01-15 09:59:46] KV cache pool initialized: 524288 tokens capacity",
    "[2025-01-15 09:59:47] Server ready. Listening on 0.0.0.0:30000",
    ""
]
with open('/app/data/server_logs/server_startup.log', 'w') as f:
    f.write('\n'.join(startup_lines))

# --- Generate benchmark data ---
for rate in REQUEST_RATES:
    rho = min(rate / BASE_SERVICE_RATE, 0.99)

    cur.execute('INSERT INTO runs (request_rate, num_requests) VALUES (?, ?)',
                (rate, NUM_REQUESTS))
    run_id = cur.lastrowid

    all_requests = []
    arrival_time = 0.0

    for i in range(NUM_REQUESTS):
        if i > 0:
            arrival_time += random.expovariate(rate)

        prompt_len = random.randint(256, 1024)
        output_len = random.randint(64, 256)

        base_ttft = prompt_len * 0.0001
        if rho < 0.95:
            mean_wait = rho / (1.0 - rho) * 0.05
            queue_wait = random.expovariate(1.0 / max(mean_wait, 0.001))
        else:
            queue_wait = random.expovariate(0.5)
        noise = abs(random.gauss(0, 0.005))
        ttft = max(0.01, base_ttft + queue_wait + noise)

        batch_factor = 1.0 + 0.3 * rho
        base_itl = 0.022 * batch_factor
        itl = [max(0.005, random.gauss(base_itl, 0.003)) for _ in range(output_len - 1)]

        latency = ttft + sum(itl)

        success = 1
        if rho >= 0.9 and random.random() < 0.03:
            success = 0

        itl_json = json.dumps([round(t, 6) for t in itl])

        cur.execute('''INSERT INTO traces
            (run_id, request_id, arrival_time, prompt_len, output_len,
             ttft, latency, success, itl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (run_id, i, round(arrival_time, 6), prompt_len, output_len,
             round(ttft, 6), round(latency, 6), success, itl_json))

        all_requests.append({
            'arrival_time': round(arrival_time, 6),
            'latency': round(latency, 6),
            'output_len': output_len,
            'success': bool(success)
        })

    # Per-run server scheduler log
    successful = [r for r in all_requests if r['success']]
    total_out_tokens = sum(r['output_len'] for r in successful)
    duration = (max(r['arrival_time'] + r['latency'] for r in all_requests)
                - min(r['arrival_time'] for r in all_requests))
    avg_running = max(1, int(rho * 200))
    token_usage = min(rho * 0.95, 0.98)

    log_lines = []
    log_lines.append("[2025-01-15 10:00:00] === Benchmark starting: rate={:.1f} req/s, num_requests={} ===".format(
        rate, NUM_REQUESTS))

    num_snapshots = min(int(duration / 5) + 1, 20)
    for snap_idx in range(num_snapshots):
        t_offset = int(snap_idx * duration / max(num_snapshots, 1))
        running = max(1, min(int(avg_running * (1.0 + 0.2 * random.gauss(0, 1))), 500))
        usage = min(token_usage * (1.0 + 0.1 * random.gauss(0, 1)), 0.99)
        queue = max(0, int(rate * 2 * random.gauss(1, 0.3)))
        throughput_inst = total_out_tokens / max(duration, 1) * (1 + 0.1 * random.gauss(0, 1))

        minutes = 1 + t_offset // 60
        seconds = t_offset % 60
        log_lines.append(
            "[2025-01-15 10:{:02d}:{:02d}] Decode batch. #running-req: {}, "
            "#token: {}, token usage: {:.2f}, cuda graph: True, "
            "gen throughput (token/s): {:.2f}, #queue-req: {}".format(
                minutes, seconds, running,
                random.randint(50000, 400000), usage,
                throughput_inst, queue
            )
        )

        if rho > 0.85 and random.random() < 0.25:
            retracted = random.randint(1, 5)
            log_lines.append(
                "[2025-01-15 10:{:02d}:{:02d}] WARNING: KV cache pool is full. "
                "Retract requests. #retracted_reqs: {}, "
                "#new_token_ratio: 0.9998 -> 1.0000".format(
                    minutes, min(seconds + 1, 59), retracted
                )
            )

    log_lines.append("[2025-01-15 10:{:02d}:00] === Benchmark complete: rate={:.1f} ===".format(
        min(1 + int(duration / 60) + 1, 59), rate))
    log_lines.append("")

    with open('/app/data/server_logs/benchmark_rate_{:.1f}.log'.format(rate), 'w') as f:
        f.write('\n'.join(log_lines))

conn.commit()
conn.close()

# --- YAML deployment configuration ---
yaml_content = """# SGLang deployment configuration
cluster:
  gpu_type: "NVIDIA H100 80GB SXM"
  gpu_memory_bytes: 85899345920
  num_gpus: 8
  interconnect: "NVLink"
  topology: "fully_connected"

server:
  model_path: "MoE-47B"
  tp_size: 2
  dp_size: 1
  mem_fraction_static: {mem_frac}
  chunked_prefill_size: 8192
  max_running_requests: 4096
  schedule_conservativeness: 1.0
  enable_metrics: true
  dtype: "bfloat16"
  port: 30000

benchmark:
  backend: "sglang"
  dataset: "synthetic-random"
  num_requests: {num_req}
  request_rates: [{rates}]
""".format(
    mem_frac=MEM_FRACTION_STATIC,
    num_req=NUM_REQUESTS,
    rates=', '.join(str(r) for r in REQUEST_RATES)
)

with open('/app/data/server_config.yaml', 'w') as f:
    f.write(yaml_content)

print("Data generation complete.")
