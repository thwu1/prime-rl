from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
LAUNCHER = ROOT / "frontierbench_sandoq" / "launch_oracle.sh"
ENVIRONMENT = ROOT / "frontierbench_sandoq" / "frontierbench.env"


def _default(name: str, text: str) -> str:
    match = re.search(rf"^{re.escape(name)}=\$\{{{re.escape(name)}:-([^}}]+)\}}$", text, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_full_oracle_launcher_passes_the_qualified_resource_clamp() -> None:
    launcher = LAUNCHER.read_text()
    environment = ENVIRONMENT.read_text()

    assert _default("SANDOQ_TASK_MAX_CPUS", environment) == "2"
    assert _default("SANDOQ_TASK_MAX_MEMORY_MB", environment) == "4096"
    assert _default("SANDOQ_TASK_MAX_STORAGE_MB", environment) == "10240"
    assert _default("FRONTIERBENCH_BUILD_ROW_ATTEMPTS", environment) == "3"
    assert 'TASK_RESOURCE_CPU_CAP="$SANDOQ_TASK_MAX_CPUS"' in launcher
    assert 'TASK_RESOURCE_MEMORY_MB_CAP="$SANDOQ_TASK_MAX_MEMORY_MB"' in launcher
    assert 'TASK_RESOURCE_STORAGE_MB_CAP="$SANDOQ_TASK_MAX_STORAGE_MB"' in launcher
    assert 'BUILD_ROW_ATTEMPTS="$FRONTIERBENCH_BUILD_ROW_ATTEMPTS"' in launcher
    assert "FRONTIERBENCH_ENFORCE_FULL_RESOURCE_GATE" not in launcher


def test_full_oracle_aggregate_can_reach_the_global_acceptance_floor() -> None:
    environment = ENVIRONMENT.read_text()

    expected = int(_default("FRONTIERBENCH_EXPECTED_TASKS", environment))
    compose = int(_default("FRONTIERBENCH_COMPOSE_TASKS", environment))
    runnable = int(_default("FRONTIERBENCH_SANDOQ_RUNNABLE_TASKS", environment))
    minimum_valid = int(_default("FRONTIERBENCH_ORACLE_MINIMUM_VALID", environment))

    assert expected == 294
    assert compose == 9
    assert runnable == expected - compose == 285
    assert runnable >= minimum_valid == 265


def test_excluded_category_boundary_is_checked_before_any_build_plan() -> None:
    launcher = LAUNCHER.read_text()

    exclusion_check = launcher.index('security_matches=$(find "$dataset_dir"')
    exclusion_failure = launcher.index('if [[ "$task_count" != "$expected_tasks" || "$security_matches" != 0 ]]')
    build_plan = launcher.index('"$project_dir/user/tianhaowu/terminal_bench_vmvm/prepare_build_plan.py"')

    assert exclusion_check < exclusion_failure < build_plan
    assert "Dataset eligibility check failed (count or excluded-category boundary)" in launcher


def test_compose_is_counted_across_all_harbor_filename_variants() -> None:
    launcher = LAUNCHER.read_text()

    for filename in ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml"):
        assert f"-name {filename}" in launcher
    assert "Pinned aggregate Compose coverage changed" in launcher
