#!/usr/bin/env python3
"""Create the constraints database for the distributed training simulation."""

import sqlite3
import os

DB_PATH = '/app/constraints.db'

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

db = sqlite3.connect(DB_PATH)

db.execute("""
CREATE TABLE strategies (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL,
    ranks INTEGER NOT NULL,
    layers INTEGER NOT NULL,
    batches INTEGER NOT NULL,
    time_limit REAL NOT NULL,
    memory_limit INTEGER NOT NULL
)
""")

db.execute("""
CREATE TABLE communication_costs (
    operation TEXT PRIMARY KEY,
    base_cost REAL NOT NULL,
    scaling_note TEXT NOT NULL
)
""")

db.execute("""
CREATE TABLE strategy_requirements (
    id INTEGER PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    req_order INTEGER NOT NULL,
    category TEXT NOT NULL,
    requirement TEXT NOT NULL,
    FOREIGN KEY (strategy_name) REFERENCES strategies(name)
)
""")

db.executemany(
    "INSERT INTO strategies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    [
        (1, 'fsdp',
         'Fully-Sharded Data Parallel: shard weights and optimizer states across ranks, use collective operations for compute phases',
         4, 6, 4, 25, 2800000),
        (2, 'gpipe',
         'GPipe pipeline schedule: partition layers into pipeline stages across ranks, schedule microbatch processing',
         4, 8, 4, 40, 4500000),
        (3, 'pipeline_fsdp',
         'Combined Pipeline Parallelism with FSDP: pipeline stages with global weight sharding across all participating ranks',
         16, 4, 4, 20, 1500000),
    ]
)

db.executemany(
    "INSERT INTO communication_costs VALUES (?, ?, ?)",
    [
        ('forward', 1.0, 'Cost scales with number of batch elements per layer'),
        ('backward', 1.0, 'Cost scales with number of batch elements per layer'),
        ('update', 0.5, 'Fixed cost per layer weight update'),
        ('allreduce', 0.3, 'Fixed cost per collective call'),
        ('allgather', 0.3, 'Fixed cost per collective call'),
        ('scatterreduce', 0.3, 'Combines allreduce then shards result'),
        ('pass_to', 0.2, 'Point-to-point send between ranks'),
        ('receive', 0.0, 'Blocks until matching pass_to completes'),
        ('loss', 0.0, 'Zero-cost gradient computation at final layer'),
    ]
)

db.executemany(
    "INSERT INTO strategy_requirements VALUES (?, ?, ?, ?, ?)",
    [
        (1, 'fsdp', 1, 'sharding',
         'Weights and optimizer states must be sharded across all ranks for storage'),
        (2, 'fsdp', 2, 'communication',
         'Use allgather to reconstruct full weights before forward and backward passes'),
        (3, 'fsdp', 3, 'communication',
         'Use scatterreduce to distribute gradient shards after backward pass'),
        (4, 'fsdp', 4, 'memory',
         'Delete gathered full weights after use to stay within memory budget'),
        (5, 'gpipe', 1, 'partitioning',
         'Evenly partition layers across ranks as contiguous pipeline stages'),
        (6, 'gpipe', 2, 'scheduling',
         'Process all microbatches forward through all stages, then all backward'),
        (7, 'gpipe', 3, 'communication',
         'Use pass_to/receive for activation and gradient transfer between adjacent stages'),
        (8, 'gpipe', 4, 'gradient',
         'Accumulate gradients across all microbatches before performing weight update'),
        (9, 'pipeline_fsdp', 1, 'mapping',
         'Pipeline stage determined by rank modulo num_stages; data parallelism via rank integer-divide num_stages'),
        (10, 'pipeline_fsdp', 2, 'sharding',
         'All ranks participate in global allgather/scatterreduce for every layer'),
        (11, 'pipeline_fsdp', 3, 'compute',
         'Only perform forward/backward computation on assigned pipeline layers; contribute empty gradients for other layers in scatterreduce'),
        (12, 'pipeline_fsdp', 4, 'storage',
         'Every rank stores a shard of every layer weight but only computes on its pipeline-assigned layers'),
    ]
)

db.commit()
db.close()
