import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest
from terminal_bench_vmvm.taskset import (
    TerminalBenchVMVMConfig,
    TerminalBenchVMVMTaskset,
    _compose_path,
    _declared_test_requirements,
    _dockerfile_startup_command,
    _environment_workdir,
)


def test_environment_workdir_defaults_and_tracks_relative_updates(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.12\nWORKDIR /workspace\nWORKDIR project\n")
    assert _environment_workdir(dockerfile) == "/workspace/project"
    assert _environment_workdir(tmp_path / "missing") == "/app"


def test_compose_path_accepts_standard_names_in_precedence_order(tmp_path: Path) -> None:
    environment = tmp_path / "environment"
    environment.mkdir()
    fallback = environment / "compose.yml"
    fallback.write_text("services: {}\n")
    assert _compose_path(tmp_path) == fallback

    preferred = environment / "docker-compose.yaml"
    preferred.write_text("services: {}\n")
    assert _compose_path(tmp_path) == preferred


def test_declared_test_requirements_parses_marked_pip_layer(tmp_path: Path) -> None:
    environment = tmp_path / "environment"
    environment.mkdir()
    (environment / "Dockerfile").write_text(
        "FROM python:3.12\n"
        "RUN pip3 install unrelated==1\n"
        "# Test dependencies prebaked so the verifier runs offline\n"
        "RUN python3 -m pip install -q pytest==8.3.4 \\\n"
        "    psycopg2-binary==2.9.10 | tail\n"
    )
    assert _declared_test_requirements(str(tmp_path)) == (
        "pytest==8.3.4",
        "psycopg2-binary==2.9.10",
    )


def test_dockerfile_startup_command_combines_exec_forms(tmp_path: Path) -> None:
    environment = tmp_path / "environment"
    environment.mkdir()
    dockerfile = environment / "Dockerfile"
    dockerfile.write_text(
        'FROM ubuntu\nENTRYPOINT ["/entrypoint.sh"]\nCMD ["sleep", "infinity"]\n'
    )
    assert _dockerfile_startup_command(str(tmp_path)) == (
        "/entrypoint.sh",
        "sleep",
        "infinity",
    )

    other = tmp_path / "other" / "environment"
    other.mkdir(parents=True)
    (other / "Dockerfile").write_text("FROM ubuntu\nCMD run-server --port 80\n")
    assert _dockerfile_startup_command(str(other.parent)) == (
        "/bin/sh",
        "-c",
        "run-server --port 80",
    )


def test_repository_mobius_archive_indexes_all_tasks() -> None:
    repository = Path(__file__).resolve().parents[4]
    with ZipFile(repository / "tb_tasks.zip") as archive:
        task_slugs = {
            parts[1]
            for name in archive.namelist()
            if len(parts := name.split("/")) == 3
            and parts[0] == "tb_tasks"
            and parts[2] == "task.toml"
        }
    assert len(task_slugs) == 2538


def test_task_file_selects_exact_tasks(tmp_path: Path) -> None:
    for slug in ("aig-coq-verification", "maxsat-vertex-cover"):
        task_dir = tmp_path / slug
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("")
        (task_dir / "instruction.md").write_text(f"Complete {slug}.\n")
    task_file = tmp_path / "oracle-valid.txt"
    task_file.write_text("aig-coq-verification\t1.0\nmaxsat-vertex-cover\n")
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=tmp_path,
            task_file=task_file,
            image_prefix="registry.invalid/terminal_bench",
            image_tag="test-revision",
            ignore_dockerfile=True,
        )
    )
    assert [task.slug for task in taskset.load_tasks()] == [
        "aig-coq-verification",
        "maxsat-vertex-cover",
    ]


def test_dataset_revision_requires_exact_clean_worktree(tmp_path: Path) -> None:
    task_dir = tmp_path / "task-a"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text("")
    (task_dir / "instruction.md").write_text("Complete task-a.\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "dataset"], check=True)
    revision = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    def taskset(expected: str) -> TerminalBenchVMVMTaskset:
        return TerminalBenchVMVMTaskset(
            TerminalBenchVMVMConfig(
                id="terminal-bench-vmvm",
                dataset_dir=tmp_path,
                dataset_revision=expected,
                image_prefix="registry.invalid/terminal_bench",
                image_tag="test-revision",
                ignore_dockerfile=True,
            )
        )

    assert [task.slug for task in taskset(revision).load_tasks()] == ["task-a"]
    with pytest.raises(ValueError, match="dataset revision mismatch"):
        taskset("0" * 40).load_tasks()

    (task_dir / "instruction.md").write_text("Changed.\n")
    with pytest.raises(ValueError, match="dataset worktree is not clean"):
        taskset(revision).load_tasks()
