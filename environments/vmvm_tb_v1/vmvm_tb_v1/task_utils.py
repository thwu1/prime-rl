# VENDORED from amaia-collab apps/sea/envs/envs/terminal_bench (snapshot 2026-06-15). Pure module, no edits.
# Copyright (c) Meta Platforms, Inc. and affiliates.

import re
from logging import getLogger
from pathlib import Path

logger = getLogger()

VMVM_REGISTRY_PREFIX = "vmvm-registry.fbinfra.net/terminal_bench/"


def extract_markdown_from_response(text: str) -> str:
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def is_v2_format(task_path: Path) -> bool:
    return (task_path / "task.toml").exists()


def load_task_config(task_path: Path) -> dict:
    if is_v2_format(task_path):
        return _load_task_config_v2(task_path)
    return _load_task_config_v1(task_path)


def _load_task_config_v1(task_path: Path) -> dict:
    import yaml
    task_yaml = task_path / "task.yaml"
    if not task_yaml.exists():
        raise FileNotFoundError(f"task.yaml not found at {task_yaml}")
    with open(task_yaml) as f:
        config = yaml.safe_load(f)
    config["workdir"] = get_workdir_from_dockerfile(task_path)
    config["_format"] = "v1"
    return config


def _load_task_config_v2(task_path: Path) -> dict:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    task_toml = task_path / "task.toml"
    with open(task_toml, "rb") as f:
        toml_data = tomllib.load(f)

    # Read instruction from instruction.md
    instruction_md = task_path / "instruction.md"
    instruction = instruction_md.read_text().strip() if instruction_md.exists() else ""

    # Map v2 fields to v1-compatible config
    metadata = toml_data.get("metadata", {})
    task_info = toml_data.get("task", {})
    environment = toml_data.get("environment", {})

    config = {
        "instruction": instruction,
        "difficulty": metadata.get("difficulty", "unknown"),
        "category": metadata.get("category", "unknown"),
        "tags": metadata.get("tags", []),
        "parser_name": "pytest",
        "max_agent_timeout_sec": metadata.get("max_agent_timeout_sec", 900.0),
        "max_test_timeout_sec": metadata.get("max_test_timeout_sec", 300.0),
        "docker_image": environment.get("docker_image", ""),
        "workdir": get_workdir_from_dockerfile(task_path),
        "_format": "v2",
    }
    return config


def get_workdir_from_dockerfile(task_path: Path) -> str:
    # v2: environment/Dockerfile, v1: Dockerfile
    dockerfile = task_path / "environment" / "Dockerfile"
    if not dockerfile.exists():
        dockerfile = task_path / "Dockerfile"
    if not dockerfile.exists():
        return "/app"
    workdir = "/app"
    for line in dockerfile.read_text().splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("WORKDIR"):
            workdir = stripped.split()[-1]
    return workdir


def get_solution_path(task_path: Path) -> tuple[Path | None, str]:
    """Returns (solution_file_path, type) where type is 'sh', 'yaml', or 'none'."""
    # v2 format: solution/solve.sh
    v2_solve = task_path / "solution" / "solve.sh"
    if v2_solve.exists():
        return v2_solve, "sh"
    # v1 format: solution.sh
    v1_solve = task_path / "solution.sh"
    if v1_solve.exists():
        return v1_solve, "sh"
    # v1 yaml format
    v1_yaml = task_path / "solution.yaml"
    if v1_yaml.exists():
        return v1_yaml, "yaml"
    return None, "none"


def get_run_tests_path(task_path: Path) -> Path | None:
    """Returns path to the test runner script."""
    # v2 format: tests/test.sh
    v2_test = task_path / "tests" / "test.sh"
    if v2_test.exists():
        return v2_test
    # v1 format: run-tests.sh
    v1_test = task_path / "run-tests.sh"
    if v1_test.exists():
        return v1_test
    return None


def get_docker_image_url(task_path: Path, task_config: dict) -> str:
    """Get the container image URL for a task.

    For v2 (harbor) format: reads docker_image from task.toml.
    For v1 format: constructs vmvm-registry URL from task name.
    """
    if task_config.get("_format") == "v2":
        docker_image = task_config.get("docker_image", "")
        if docker_image:
            return docker_image
    # Fallback to vmvm registry
    return f"{VMVM_REGISTRY_PREFIX}{task_path.name}:latest"


def get_terminal_bench_vmvm_image_url(task_name: str) -> str:
    return f"{VMVM_REGISTRY_PREFIX}{task_name}:latest"


def limit_output_length(text: str, max_length: int = 15000) -> str:
    if len(text) <= max_length:
        return text
    half = max_length // 2
    elided = len(text) - max_length
    return f"{text[:half]}\n\n[... {elided} characters elided ...]\n\n{text[-half:]}"
