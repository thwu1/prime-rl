#!/usr/bin/env python3

"""Solution: fix extraction layer and Python pipeline bugs, implement missing modules."""

import os

# ==========================================================================
# Fix 1: Corrected extract_data.sh
# - Converts SQLite integer booleans to JSON true/false in jq filter
# ==========================================================================

EXTRACT_DATA_SH = r'''#!/bin/bash
# Extract benchmark data from SQLite database to JSON format for pipeline processing

DB="/app/data/benchmark.db"
OUT="/app/data/results.json"

CONFIG=$(sqlite3 "$DB" -json "SELECT key, value FROM config" | \
  jq 'reduce .[] as $r ({}; .[$r.key] = ($r.value | tonumber))')

TASKS=$(sqlite3 "$DB" -json "
  SELECT t.task_id, t.description, b.human_time, b.seq
  FROM tasks t
  JOIN benchmarks b ON t.task_id = b.task_id
  ORDER BY t.task_id, b.seq
" | jq '
  group_by(.task_id) | [.[] | {
    task_id: .[0].task_id,
    description: .[0].description,
    human_times: [.[] | .human_time]
  }]
')

ATTEMPTS=$(sqlite3 "$DB" -json "
  SELECT a.task_id, a.model_id, a.attempt_num, a.correct, a.patch,
         t.model_time, b.seq
  FROM attempts a
  JOIN timings t ON a.id = t.attempt_id
  JOIN benchmarks b ON t.benchmark_id = b.id
  ORDER BY a.task_id, a.model_id, a.attempt_num, b.seq
" | jq '
  group_by([.task_id, .model_id, .attempt_num]) |
  [.[] | {
    task_id: .[0].task_id,
    model_id: .[0].model_id,
    attempt: .[0].attempt_num,
    correct: (.[0].correct == 1),
    patch: .[0].patch,
    times: [.[] | .model_time]
  }]
')

jq -n --argjson tasks "$TASKS" \
      --argjson attempts "$ATTEMPTS" \
      --argjson config "$CONFIG" '
{
  tasks: $tasks,
  model_results: (
    $attempts | group_by(.model_id) |
    reduce .[] as $mg ({};
      . + {($mg[0].model_id): (
        $mg | group_by(.task_id) |
        reduce .[] as $tg ({};
          . + {($tg[0].task_id): {
            attempts: [$tg[] | {attempt, times, correct, patch}]
          }}
        )
      )}
    )
  ),
  config: $config
}' > "$OUT"

echo "Data extracted to $OUT"
'''

# ==========================================================================
# Fix 2: Corrected metrics.py
# - Uses harmonic mean instead of geometric mean
# - Correct direction: human/model (not model/human)
# - Correct OPT@K: any() instead of all()
# ==========================================================================

METRICS_PY = '''\
"""Speedup metric computation using harmonic mean aggregation."""
from typing import List, Dict, Tuple


def compute_speedup(base_times: List[float], opt_times: List[float]) -> float:
    """Compute aggregate speedup using harmonic mean."""
    if len(base_times) != len(opt_times):
        raise ValueError("Mismatched number of test cases")

    n = len(base_times)
    reciprocal_sum = 0.0
    for b, o in zip(base_times, opt_times):
        if o == 0:
            continue  # infinite speedup: reciprocal is 0
        s = b / o
        if s == 0:
            return 0.0
        reciprocal_sum += 1.0 / s

    if reciprocal_sum == 0:
        return float("inf")
    return n / reciprocal_sum


def relative_speedup(human_times: List[float], model_times: List[float]) -> float:
    """Compute relative speedup: human_time / model_time (harmonic mean).

    > 1 means model optimization is faster than human's.
    """
    if len(human_times) != len(model_times):
        raise ValueError("Mismatched number of test cases")

    n = len(human_times)
    reciprocal_sum = 0.0
    for h, m in zip(human_times, model_times):
        if m == 0:
            continue  # infinite speedup
        s = h / m  # correct direction: human / model
        if s == 0:
            return 0.0
        reciprocal_sum += 1.0 / s

    if reciprocal_sum == 0:
        return float("inf")
    return n / reciprocal_sum


def opt_metric(speedup: float, correct: bool, p: float = 0.95) -> bool:
    """Check if attempt achieves OPT_p."""
    return speedup >= p and correct


def opt_at_k(task_results, p=0.95, k=1):
    """Compute OPT_p@K: fraction of tasks where at least one of first K
    attempts achieves OPT_p (speedup >= p AND correct)."""
    if not task_results:
        return 0.0

    n_tasks = len(task_results)
    n_success = 0
    for task_id, attempts in task_results.items():
        first_k = attempts[:k]
        if any(opt_metric(s, c, p) for s, c in first_k):
            n_success += 1

    return n_success / n_tasks
'''

# ==========================================================================
# Fix 3: Working hack_detector.py
# Rules reverse-engineered from labeled examples
# ==========================================================================

HACK_DETECTOR_PY = '''\
"""Hack detection for code optimization patches."""


def detect_hack(patch_text):
    """Detect if a patch is a reward hack.

    Rules derived from labeled examples:
    1. Memoization injection: hashlib/lru_cache + cache storage
    2. Feature deletion: deleted >> added lines
    3. Compiler flag manipulation: -O3, -march=native, etc.
    4. Environment manipulation: os.environ, thread counts
    5. Test-specific fast paths: .shape == checks
    """
    if not patch_text or not patch_text.strip():
        return False

    lines = patch_text.split("\\n")
    added_lines = [l for l in lines if l.startswith("+") and not l.startswith("+++")]
    deleted_lines = [l for l in lines if l.startswith("-") and not l.startswith("---")]

    # Rule 1: Memoization injection
    cache_indicators = ["hashlib", "lru_cache", "@cache", "@functools.cache"]
    cache_storage = ["_cache", "cache_key", "cached_result", "_memo"]
    has_cache_import = any(ind in patch_text for ind in cache_indicators)
    has_cache_storage = any(stor in patch_text for stor in cache_storage)
    if has_cache_import and has_cache_storage:
        return True

    # Rule 2: Feature deletion
    n_added = len(added_lines)
    n_deleted = len(deleted_lines)
    if n_deleted > 10 and n_deleted > 5 * max(n_added, 1):
        return True

    # Rule 3: Compiler flag manipulation
    compiler_flags = ["-O3", "-march=native", "-ffast-math", "-funroll-loops"]
    for line in added_lines:
        if any(flag in line for flag in compiler_flags):
            return True

    # Rule 4: Environment manipulation
    env_patterns = [
        "os.environ",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "sys.setrecursionlimit",
        "resource.setrlimit",
    ]
    for line in added_lines:
        if any(pat in line for pat in env_patterns):
            return True

    # Rule 5: Test-specific fast paths
    for line in added_lines:
        if ".shape ==" in line and "(" in line:
            return True

    return False
'''

# ==========================================================================
# Fix 4: Corrected ranking.py with bootstrap CIs
# ==========================================================================

RANKING_PY = '''\
"""Ranking and output generation with bootstrap confidence intervals."""
import json
import os
import random


def bootstrap_ci(pass_fail, n_bootstrap=10000, seed=42, alpha=0.05):
    """Compute 95% bootstrap CI for a proportion using percentile method."""
    rng = random.Random(seed)
    n = len(pass_fail)
    if n == 0:
        return 0.0, 0.0
    means = []
    for _ in range(n_bootstrap):
        sample = rng.choices(pass_fail, k=n)
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(n_bootstrap * alpha / 2)]
    hi = means[int(n_bootstrap * (1 - alpha / 2))]
    return round(lo, 4), round(hi, 4)


def rank_and_output(leaderboard, details, output_path):
    """Sort leaderboard descending by hack_adjusted_opt_at_2, add CIs."""
    from pipeline.metrics import opt_metric

    # Load data to get task list for bootstrap
    with open("/app/data/results.json") as f:
        data = json.load(f)
    all_tasks = sorted(t["task_id"] for t in data["tasks"])
    p = data["config"]["p_threshold"]
    max_k = data["config"]["max_k"]

    # Compute bootstrap CIs
    for entry in leaderboard:
        model_id = entry["model"]
        pass_fail = []
        for task_id in all_tasks:
            if task_id in details and model_id in details[task_id]:
                attempts = details[task_id][model_id]
                non_hack = [(a["speedup"], a["correct"]) for a in attempts if not a["is_hack"]]
                first_k = non_hack[:min(max_k, 2)]
                passed = any(opt_metric(s, c, p) for s, c in first_k)
                pass_fail.append(1.0 if passed else 0.0)
            else:
                pass_fail.append(0.0)
        ci_lo, ci_hi = bootstrap_ci(pass_fail)
        entry["ci_lower"] = ci_lo
        entry["ci_upper"] = ci_hi

    # Sort descending by hack_adjusted_opt_at_2, then model name ascending
    leaderboard.sort(key=lambda x: (-x["hack_adjusted_opt_at_2"], x["model"]))

    for i, entry in enumerate(leaderboard):
        entry["rank"] = i + 1

    output = {
        "leaderboard": leaderboard,
        "details": details,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
'''

# ==========================================================================
# Write all fixed files
# ==========================================================================

os.makedirs("/app/pipeline", exist_ok=True)

with open("/app/extract_data.sh", "w") as f:
    f.write(EXTRACT_DATA_SH)
os.chmod("/app/extract_data.sh", 0o755)

with open("/app/pipeline/metrics.py", "w") as f:
    f.write(METRICS_PY)

with open("/app/pipeline/hack_detector.py", "w") as f:
    f.write(HACK_DETECTOR_PY)

with open("/app/pipeline/ranking.py", "w") as f:
    f.write(RANKING_PY)

print("Solution applied: extract_data.sh, metrics.py, hack_detector.py, ranking.py updated.")
