-- Database schema for MoE inference cluster benchmarks
-- Database file: /app/cluster.db

CREATE TABLE gpu_specs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                -- GPU model identifier
    sm_count INTEGER NOT NULL,         -- Number of streaming multiprocessors
    memory_gb REAL NOT NULL,           -- GPU HBM capacity in GB (1 GB = 10^9 bytes)
    hbm_bandwidth_gbps REAL NOT NULL,  -- Peak HBM bandwidth in GB/s
    peak_bf16_tflops REAL NOT NULL     -- Peak BF16 throughput in TFLOPS
);

CREATE TABLE model_configs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                -- Model name
    num_layers INTEGER NOT NULL,       -- Number of transformer layers (each has KV cache)
    hidden_dim INTEGER NOT NULL,       -- Model hidden dimension
    num_heads INTEGER NOT NULL,        -- Number of query attention heads (MQA: 1 KV head)
    d_nope INTEGER NOT NULL,           -- Non-positional (NoPE) dimension of KV latent
    d_rope INTEGER NOT NULL,           -- Rotary positional encoding dimension of KV latent
    d_v INTEGER NOT NULL,              -- Value head dimension (V is derived from KV latent)
    num_experts INTEGER NOT NULL,      -- Total number of MoE experts
    topk INTEGER NOT NULL,             -- Experts activated per token
    ffn_intermediate INTEGER NOT NULL, -- FFN intermediate dimension per expert (SwiGLU)
    weight_memory_gb REAL NOT NULL     -- Total model weight memory in GB
);

CREATE TABLE kv_cache_formats (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                -- Format short name used in workloads
    layout_type TEXT NOT NULL           -- Layout type key (cross-reference with source code)
);

CREATE TABLE workloads (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                    -- Workload scenario name
    model_config_id INTEGER NOT NULL,      -- FK -> model_configs
    gpu_spec_id INTEGER NOT NULL,          -- FK -> gpu_specs
    kv_format_id INTEGER NOT NULL,         -- FK -> kv_cache_formats
    batch_size INTEGER NOT NULL,           -- Number of concurrent decoding sequences
    seq_len INTEGER NOT NULL,              -- Sequence length (KV cache depth per sequence)
    use_fp8_dispatch INTEGER NOT NULL      -- 1 = FP8 EP dispatch, 0 = BF16 EP dispatch
);

CREATE TABLE ep_measurements (
    gpu_spec_id INTEGER NOT NULL,          -- FK -> gpu_specs
    num_sms INTEGER NOT NULL,              -- SMs allocated to EP communication
    dispatch_bw_gbps REAL NOT NULL,        -- Measured dispatch bandwidth in GB/s
    combine_bw_gbps REAL NOT NULL,         -- Measured combine bandwidth in GB/s
    PRIMARY KEY (gpu_spec_id, num_sms)
);
