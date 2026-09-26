from __future__ import annotations

import os
import subprocess
from pathlib import Path

WORKFLOW_DIR = Path(__file__).parents[1]
INNER = WORKFLOW_DIR / "run_direct_kimi_sandoq_stage.sh"
BARRIER = WORKFLOW_DIR / "run_kimi_tb4_shared_union_lane.sh"
LAUNCHER = (
    WORKFLOW_DIR
    / "configs/eval/servers/cpu-132-021_8103"
    / "run_tb4_kimi_k3_miniswe246_shared_union_cpu-132-021_8103.sbatch"
)


def test_shared_union_shell_entrypoints_are_executable_and_parse() -> None:
    for path in (INNER, BARRIER, LAUNCHER):
        assert os.access(path, os.X_OK)
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_shared_union_owns_one_router_and_runs_both_lanes() -> None:
    launcher = LAUNCHER.read_text(encoding="utf-8")

    assert "#SBATCH --signal=B:TERM@1800" in launcher
    assert '[[ "$job_wall_limit" == 4-00:00:00 ]]' in launcher
    assert launcher.count('python3 "$workflow_dir/direct_kimi_workers.py" prepare') == 1
    assert launcher.count('python3 "$workflow_dir/direct_kimi_router.py"') == 1
    assert launcher.count('python3 "$workflow_dir/kimi_endpoint_load_gate.py"') == 1
    assert launcher.count('python3 "$workflow_dir/kimi_endpoint_walltime_gate.py" capture') == 2
    assert "DIRECT_KIMI_ROLLOUT_CONCURRENCY=48" in launcher
    assert "DIRECT_KIMI_ROLLOUT_CONCURRENCY=11" in launcher
    assert "DIRECT_KIMI_ROUTER_CAPACITY_PROFILE=sandoq-c64-w2-v1" in launcher
    assert "--concurrency 64 --lease-create-cap 4" in launcher
    assert 'setsid env "${sandoq_env[@]}"' in launcher
    assert 'kill -TERM -- "-$sandoq_pid"' in launcher
    assert "SANDOQ_PROVIDER_TERMINATION_GRACE_SECONDS=600" in launcher
    assert 'wait_pid_bounded "$vmvm_pid" 420 1' in launcher
    assert 'wait_pid_bounded "$sandoq_pid" 660 1' in launcher
    assert 'while kill -0 -- "$target"' in launcher
    assert 'drain_recorded_evaluator "${vmvm_output:-/nonexistent}/control/evaluator.pgid" 420' in launcher
    assert "emergency_sandoq_cleanup" in launcher
    assert '--output-dir "$fallback_dir" --concurrency 32 --live-only' in launcher
    assert 'source_wal="$source_output/control/sandoq-pool.wal.jsonl"' in launcher
    assert 'for lane_output in "$sandoq_output" "$vmvm_output"; do' in launcher
    assert 'python3 "$workflow_dir/certify_kimi_tb4_miniswe246_union.py" merge' in launcher
    assert "sbatch " not in launcher


def test_shared_union_barrier_supplies_precaptured_evidence() -> None:
    barrier = BARRIER.read_text(encoding="utf-8")
    inner = INNER.read_text(encoding="utf-8")

    assert "KIMI_SHARED_UNION_WALLTIME_SHA_FILE" in barrier
    assert "KIMI_SHARED_UNION_LOAD_GATE_SHA_FILE" in barrier
    assert "DIRECT_KIMI_PRECAPTURED_ENDPOINT_WALLTIME_GATE_SHA256" in barrier
    assert "DIRECT_KIMI_PRECAPTURED_ENDPOINT_LOAD_GATE_SHA256" in barrier
    assert barrier.index("DIRECT_KIMI_PRECAPTURED_ENDPOINT_LOAD_GATE_SHA256") < barrier.index(
        'exec /usr/bin/bash -p "$workflow_dir/run_direct_kimi_sandoq_stage.sh"'
    )
    assert "DIRECT_KIMI_PRECAPTURED_ENDPOINT_WALLTIME_GATE" in inner
    assert "DIRECT_KIMI_PRECAPTURED_ENDPOINT_LOAD_GATE" in inner
    assert "maximum_age_seconds=900" in inner
    assert 'eval_pgid_file="$output_dir/control/evaluator.pgid"' in inner
    assert 'if [[ "$eval_stop_requested" == 1 ]]; then' in inner
    assert inner.index("eval_pid=$!") < inner.index('if [[ "$eval_stop_requested" == 1 ]]; then')


def test_shared_union_uses_lane_specific_walltime_receipts() -> None:
    launcher = LAUNCHER.read_text(encoding="utf-8")

    assert "--profile tb4-extended-c48-w2-two-wave-v1" in launcher
    assert "--minimum-remaining-seconds 345600 --task-count 52" in launcher
    assert "--profile tb4-extended-vmvm-union11-c11-v1" in launcher
    assert "--minimum-remaining-seconds 345600 --task-count 11" in launcher
    assert 'DIRECT_KIMI_PRECAPTURED_ENDPOINT_LOAD_GATE="$load_gate"' in launcher
