CREATE TABLE hardware (
    bandwidth REAL NOT NULL,
    latency REAL NOT NULL,
    hidden_dim INTEGER NOT NULL,
    seq_length INTEGER NOT NULL
);

CREATE TABLE strategy_config (
    name TEXT PRIMARY KEY,
    ranks INTEGER NOT NULL,
    layers INTEGER NOT NULL,
    batches INTEGER NOT NULL,
    max_time REAL NOT NULL,
    max_peak_memory REAL NOT NULL,
    description TEXT
);

INSERT INTO hardware VALUES (1310720.0, 0.1, 512, 256);
INSERT INTO strategy_config VALUES ('ddp', 4, 4, 4, 15.0, 3500000.0, 'Distributed Data Parallel - replicate model on each rank');
INSERT INTO strategy_config VALUES ('fsdp', 4, 6, 4, 25.0, 2800000.0, 'Fully Sharded Data Parallel (ZeRO-3) - shard weights/grads/optimizer across ranks');
INSERT INTO strategy_config VALUES ('pipeline_fsdp', 16, 4, 4, 22.0, 1500000.0, 'Pipeline Parallelism + FSDP - partition layers into stages with sharded weights');
