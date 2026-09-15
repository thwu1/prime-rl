#!/usr/bin/env python3
"""Generate memory traces and YAML configurations for the scheduling evaluation."""

import os
import random

# ─── Trace Generation ───

TRACE_DIR = "/app/traces"
CONFIG_DIR = "/app/configs"
NUM_INSTS = 100000
DISTANCE = 10
CACHE_LINE_SIZE = 64

os.makedirs(TRACE_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

# Sequential streaming trace
with open(os.path.join(TRACE_DIR, "sequential.trace"), "w") as f:
    addr = 0
    generated = 0
    while generated < NUM_INSTS:
        f.write(f"{DISTANCE} {addr}\n")
        addr += CACHE_LINE_SIZE
        generated += DISTANCE

print(f"Generated sequential trace: {NUM_INSTS // DISTANCE} requests")

# Random access trace (deterministic seed=42)
random.seed(42)
with open(os.path.join(TRACE_DIR, "random.trace"), "w") as f:
    generated = 0
    while generated < NUM_INSTS:
        addr = random.getrandbits(30)
        f.write(f"{DISTANCE} {addr}\n")
        generated += DISTANCE

print(f"Generated random trace: {NUM_INSTS // DISTANCE} requests")

# ─── YAML Configuration Generation ───

CONFIG_TEMPLATE = """\
Frontend:
  impl: SimpleO3
  clock_ratio: 8
  num_expected_insts: 100000
  traces:
    - {trace_path}
  Translation:
    impl: RandomTranslation
    max_addr: 2147483648

MemorySystem:
  impl: GenericDRAM
  clock_ratio: 3
  DRAM:
    impl: DDR4
    org:
      preset: DDR4_8Gb_x8
      channel: 1
      rank: 1
    timing:
      preset: DDR4_2400R
  Controller:
    impl: Generic
    Scheduler:
      impl: {scheduler}
    RefreshManager:
      impl: AllBank
    RowPolicy:
      impl: ClosedRowPolicy
      cap: 4
  AddrMapper:
    impl: RoBaRaCoCh
"""

for scheduler in ["FRFCFS", "FCFS"]:
    for workload, trace_file in [
        ("sequential", os.path.join(TRACE_DIR, "sequential.trace")),
        ("random", os.path.join(TRACE_DIR, "random.trace")),
    ]:
        name = f"{scheduler.lower()}_{workload}"
        config = CONFIG_TEMPLATE.format(
            trace_path=trace_file,
            scheduler=scheduler,
        )
        config_path = os.path.join(CONFIG_DIR, f"{name}.yaml")
        with open(config_path, "w") as f:
            f.write(config)
        print(f"Generated config: {config_path}")

print("Setup complete.")
