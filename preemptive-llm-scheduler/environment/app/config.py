# LLM Inference Serving Simulator Configuration

import json
import os

# Timing parameters (milliseconds)
PREFILL_TIME_PER_TOKEN_MS = 0.05   # Time per input token during prefill
DECODE_TIME_PER_TOKEN_MS = 1.0     # Time per output token during decode
CONTEXT_SWITCH_OVERHEAD_MS = 2.0   # Fixed overhead per preemption context switch

# GPU memory parameters — paged allocation
GPU_MEMORY_BYTES = 16 * 1024 * 1024    # 16 MB total GPU KV-cache memory
KV_CACHE_BYTES_PER_TOKEN = 4096        # 4 KB per token of KV cache
PAGE_SIZE_TOKENS = 16                   # Tokens per KV-cache page (block)

# Derived constants
PAGE_SIZE_BYTES = PAGE_SIZE_TOKENS * KV_CACHE_BYTES_PER_TOKEN   # 64 KB per page
TOTAL_PAGES = GPU_MEMORY_BYTES // PAGE_SIZE_BYTES                # 256 pages

# Remote memory bandwidth (disaggregated memory over RDMA fabric)
# Must be calibrated before running the simulator.
#
# Calibration procedure:
#   1. Measure localhost bandwidth:  iperf3 -s -D && iperf3 -c 127.0.0.1 -t 2 -J
#   2. Parse measured Gbps from JSON output
#   3. Compute:  remote_memory_bandwidth_mb_s = measured_gbps * 1000 / 50
#      (models RDMA fabric bandwidth as 1/50 of raw TCP throughput)
#   4. Clamp to range [500, 3000]
#   5. Write calibration.json in this directory with keys:
#        measured_bandwidth_gbps   (float)
#        remote_memory_bandwidth_mb_s  (float)

_CALIBRATION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")

_remote_bw_cache = None


def get_remote_bandwidth():
    """Load calibrated remote memory bandwidth. Raises if not calibrated."""
    global _remote_bw_cache
    if _remote_bw_cache is None:
        if not os.path.exists(_CALIBRATION_PATH):
            raise FileNotFoundError(
                f"Calibration file not found: {_CALIBRATION_PATH}\n"
                "Run bandwidth calibration first — see config.py for instructions."
            )
        with open(_CALIBRATION_PATH) as f:
            data = json.load(f)
        _remote_bw_cache = float(data["remote_memory_bandwidth_mb_s"])
    return _remote_bw_cache


# Workload parameters
NUM_REQUESTS = 500
ARRIVAL_RATE = 30.0    # requests per second (Poisson)
RANDOM_SEED = 42

# SLO tier deadline multipliers (of optimal single-request completion time)
SLO_DEADLINE_MULTIPLIERS = {
    0: 8.0,    # Latency-critical
    1: 25.0,   # Interactive
    2: 80.0,   # Batch
}
