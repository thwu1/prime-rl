#!/usr/bin/env python3
"""Initialize the benchmark SQLite database for the MoE cluster analysis task."""
import sqlite3

db = sqlite3.connect('/app/cluster.db')
c = db.cursor()

c.executescript('''
CREATE TABLE gpu_specs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sm_count INTEGER NOT NULL,
    memory_gb REAL NOT NULL,
    hbm_bandwidth_gbps REAL NOT NULL,
    peak_bf16_tflops REAL NOT NULL
);

CREATE TABLE model_configs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    num_layers INTEGER NOT NULL,
    hidden_dim INTEGER NOT NULL,
    num_heads INTEGER NOT NULL,
    d_nope INTEGER NOT NULL,
    d_rope INTEGER NOT NULL,
    d_v INTEGER NOT NULL,
    num_experts INTEGER NOT NULL,
    topk INTEGER NOT NULL,
    ffn_intermediate INTEGER NOT NULL,
    weight_memory_gb REAL NOT NULL
);

CREATE TABLE kv_cache_formats (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    layout_type TEXT NOT NULL
);

CREATE TABLE workloads (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    model_config_id INTEGER NOT NULL REFERENCES model_configs(id),
    gpu_spec_id INTEGER NOT NULL REFERENCES gpu_specs(id),
    kv_format_id INTEGER NOT NULL REFERENCES kv_cache_formats(id),
    batch_size INTEGER NOT NULL,
    seq_len INTEGER NOT NULL,
    use_fp8_dispatch INTEGER NOT NULL
);

CREATE TABLE ep_measurements (
    gpu_spec_id INTEGER NOT NULL REFERENCES gpu_specs(id),
    num_sms INTEGER NOT NULL,
    dispatch_bw_gbps REAL NOT NULL,
    combine_bw_gbps REAL NOT NULL,
    PRIMARY KEY (gpu_spec_id, num_sms)
);
''')

# GPU specs
c.execute("INSERT INTO gpu_specs VALUES (1, 'H800_SXM5', 132, 80.0, 3350.0, 990.0)")

# Model configs
c.execute("""INSERT INTO model_configs VALUES
    (1, 'deepseek_v32', 61, 7168, 128, 512, 64, 512, 256, 8, 2048, 22.0)""")
c.execute("""INSERT INTO model_configs VALUES
    (2, 'deepseek_m1', 48, 5120, 64, 448, 64, 448, 128, 6, 1536, 12.0)""")

# KV cache formats
c.execute("INSERT INTO kv_cache_formats VALUES (1, 'bf16', 'bf16')")
c.execute("INSERT INTO kv_cache_formats VALUES (2, 'fp8_v32', 'V32_FP8Sparse')")
c.execute("INSERT INTO kv_cache_formats VALUES (3, 'fp8_m1', 'MODEL1_FP8Sparse')")

# Workloads
c.execute("""INSERT INTO workloads VALUES
    (1, 'short_ctx_fp8', 1, 1, 2, 256, 4096, 1)""")
c.execute("""INSERT INTO workloads VALUES
    (2, 'long_ctx_bf16', 1, 1, 1, 128, 8192, 0)""")
c.execute("""INSERT INTO workloads VALUES
    (3, 'm1_fp8', 2, 1, 3, 512, 2048, 1)""")
c.execute("""INSERT INTO workloads VALUES
    (4, 'ultra_long', 1, 1, 2, 64, 131072, 1)""")

# EP bandwidth measurements (H800 NVLink 8-GPU topology)
ep_data = [
    (1, 4,  180.0, 195.0),
    (1, 8,  320.0, 340.0),
    (1, 16, 520.0, 545.0),
    (1, 24, 643.0, 675.0),
    (1, 32, 690.0, 710.0),
    (1, 48, 715.0, 730.0),
    (1, 64, 726.0, 740.0),
]
for gpu_id, sms, d_bw, c_bw in ep_data:
    c.execute("INSERT INTO ep_measurements VALUES (?, ?, ?, ?)",
              (gpu_id, sms, d_bw, c_bw))

db.commit()
db.close()
print("Database initialized at /app/cluster.db")
