#!/usr/bin/env python
"""Preserve best SFT checkpoints and launch VMVM DeepSWE evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
VALIDATION_RE = re.compile(r"Validation \| Step (?P<step>\d+) \| Loss (?P<loss>[0-9.eE+-]+)")
TRAIN_STEP_RE = re.compile(r"Step (?P<step>\d+) \|.*?\| Loss (?P<loss>[0-9.eE+-]+)")
FATAL_RE = re.compile(
    r"Traceback|CUDA out of memory|OutOfMemoryError|ChildFailedError|"
    r"NCCL.*(?:error|watchdog)|Segmentation fault",
    re.IGNORECASE,
)
ACTIVE_STATES = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED"}
CANONICAL_MODEL = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"
TASKS_PATH = "/checkpoint/ram/tianhaowu/deepswe_eval/deep-swe/tasks"
PROJECT_DIR = Path("/storage/home/tianhaowu/prime-rl")
INFERENCE_ENV = "/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft"
INFERENCE_TEMPLATE = PROJECT_DIR / "user/tianhaowu/fair-sc-3/templates/multi_node_inference_nemotron.sbatch.j2"
EVAL_SBATCH = PROJECT_DIR / "user/tianhaowu/deepswe_modal/submit_eval.sbatch"


@dataclass(frozen=True)
class RunSpec:
    label: str
    job_id: int
    run_dir: Path


def now() -> str:
    return datetime.now(UTC).isoformat()


def parse_run(value: str) -> RunSpec:
    parts = value.split("=", maxsplit=2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("run must be LABEL=JOB_ID=RUN_DIR")
    label, job_id, run_dir = parts
    if not re.fullmatch(r"[a-z0-9-]+", label):
        raise argparse.ArgumentTypeError("run label must contain lowercase letters, numbers, or hyphens")
    return RunSpec(label=label, job_id=int(job_id), run_dir=Path(run_dir).resolve())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=parse_run, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--launch-generation", type=int, default=1)
    return parser.parse_args()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def command(args: list[str], *, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        args,
        cwd=PROJECT_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def scheduler_status(job_id: int) -> dict[str, Any]:
    queued = subprocess.run(
        ["squeue", "-h", "-j", str(job_id), "-o", "%T|%M|%R|%N"],
        check=False,
        capture_output=True,
        text=True,
    )
    if queued.returncode == 0 and queued.stdout.strip():
        state, elapsed, reason, nodes = queued.stdout.strip().split("|", maxsplit=3)
        return {
            "state": state,
            "elapsed": elapsed,
            "exit_code": "",
            "restarts": 0,
            "reason": reason if state == "PENDING" else "",
            "nodes": nodes,
        }

    fields = command(
        [
            "sacct",
            "-X",
            "-n",
            "-P",
            "-j",
            str(job_id),
            "--format=State,ExitCode,Elapsed,Restarts,NodeList",
        ]
    ).splitlines()
    if not fields:
        return {
            "state": "UNKNOWN",
            "elapsed": "",
            "exit_code": "",
            "restarts": 0,
            "reason": "",
            "nodes": "",
        }
    state, exit_code, elapsed, restarts, nodes = fields[0].split("|", maxsplit=4)
    return {
        "state": state.split("+")[0],
        "elapsed": elapsed,
        "exit_code": exit_code,
        "restarts": int(restarts or 0),
        "reason": "",
        "nodes": nodes,
    }


def load_run_config(spec: RunSpec) -> dict[str, Any]:
    config_path = spec.run_dir / "configs/sft.toml"
    with config_path.open("rb") as file:
        config = tomllib.load(file)
    return {
        "config_path": str(config_path),
        "max_steps": int(config["max_steps"]),
        "validation_interval": int(config["val"]["interval"]),
        "checkpoint_interval": int(config["ckpt"]["interval"]),
        "checkpoint_keep_last": int(config["ckpt"]["keep_last"]),
        "base_model_path": str(Path(config["model"]["name"]).resolve()),
        "validation_data": config["val"]["data"]["name"],
    }


def parse_trainer_log(spec: RunSpec) -> dict[str, Any]:
    log_path = spec.run_dir / "logs/trainer.log"
    text = ANSI_RE.sub("", log_path.read_text(errors="replace")) if log_path.is_file() else ""
    validations: dict[int, float] = {}
    for match in VALIDATION_RE.finditer(text):
        validations[int(match["step"])] = float(match["loss"])
    steps = list(TRAIN_STEP_RE.finditer(text))
    latest_train = None
    if steps:
        latest_train = {"step": int(steps[-1]["step"]), "loss": float(steps[-1]["loss"])}
    return {
        "log_path": str(log_path),
        "latest_train": latest_train,
        "validations": [{"step": step, "loss": loss} for step, loss in sorted(validations.items())],
        "fatal_matches": list(dict.fromkeys(match.group(0) for match in FATAL_RE.finditer(text)))[:10],
        "finished_marker": "SFT trainer finished!" in text,
    }


def stable_checkpoint_steps(spec: RunSpec) -> list[int]:
    steps = []
    for marker in (spec.run_dir / "weights").glob("step_*/STABLE"):
        step_text = marker.parent.name.removeprefix("step_")
        if step_text.isdigit():
            steps.append(int(step_text))
    return sorted(steps)


def file_inventory(path: Path) -> tuple[list[str], int]:
    files = sorted(str(item.relative_to(path)) for item in path.rglob("*") if item.is_file() and not item.is_symlink())
    return files, sum((path / item).stat().st_size for item in files)


def preserve_best_checkpoint(spec: RunSpec, candidate: dict[str, Any]) -> dict[str, Any]:
    preserve_root = spec.run_dir / "best_val_weights"
    preserve_root.mkdir(parents=True, exist_ok=True)
    manifest_path = preserve_root / "best.json"
    if manifest_path.is_file():
        current = json.loads(manifest_path.read_text())
        if current["step"] == candidate["step"] and current["loss"] == candidate["loss"]:
            preserved_path = Path(current["preserved_path"])
            if (preserved_path / "STABLE").is_file():
                return current

    source = spec.run_dir / "weights" / f"step_{candidate['step']}"
    if not (source / "STABLE").is_file():
        raise RuntimeError(f"best validation checkpoint is no longer available: {source}")

    destination = preserve_root / source.name
    if not destination.exists():
        temporary = preserve_root / f".{source.name}.{os.getpid()}.tmp"
        if temporary.exists():
            raise FileExistsError(f"temporary checkpoint snapshot already exists: {temporary}")
        shutil.copytree(source, temporary, copy_function=os.link, symlinks=True)
        source_files, source_bytes = file_inventory(source)
        destination_files, destination_bytes = file_inventory(temporary)
        if source_files != destination_files or source_bytes != destination_bytes:
            raise RuntimeError(f"hardlink checkpoint inventory mismatch for {source}")
        for relative_path in source_files:
            if not os.path.samefile(source / relative_path, temporary / relative_path):
                raise RuntimeError(f"checkpoint snapshot is not hardlinked: {relative_path}")
        os.replace(temporary, destination)
    else:
        source_files, source_bytes = file_inventory(source)
        destination_files, _ = file_inventory(destination)
        destination_files = [item for item in destination_files if item != "PRESERVED.json"]
        destination_bytes = sum((destination / item).stat().st_size for item in destination_files)
        if source_files != destination_files or source_bytes != destination_bytes:
            raise RuntimeError(f"existing checkpoint snapshot inventory mismatch for {destination}")
        for relative_path in source_files:
            if not os.path.samefile(source / relative_path, destination / relative_path):
                raise RuntimeError(f"existing checkpoint snapshot is not hardlinked: {relative_path}")

    manifest = {
        "created_at": now(),
        "job_id": spec.job_id,
        "label": spec.label,
        "loss": candidate["loss"],
        "preserved_path": str(destination),
        "source_path": str(source),
        "step": candidate["step"],
        "file_count": len(source_files),
        "total_bytes": source_bytes,
    }
    atomic_write_json(destination / "PRESERVED.json", manifest)
    previous = json.loads(manifest_path.read_text()) if manifest_path.is_file() else None
    atomic_write_json(manifest_path, manifest)
    temporary_link = preserve_root / f".current.{os.getpid()}.tmp"
    temporary_link.symlink_to(destination.name)
    os.replace(temporary_link, preserve_root / "current")

    if previous is not None and previous.get("preserved_path") != str(destination):
        previous_path = Path(previous["preserved_path"])
        if previous_path.parent != preserve_root or not previous_path.name.startswith("step_"):
            raise RuntimeError(f"refusing to remove unexpected previous snapshot: {previous_path}")
        if previous_path.exists():
            shutil.rmtree(previous_path)
    return manifest


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_tokenizer(checkpoint: Path, base_model: Path) -> dict[str, str]:
    tokenizer_files = ("tokenizer.json", "chat_template.jinja")
    hashes = {}
    for name in tokenizer_files:
        checkpoint_file = checkpoint / name
        base_file = base_model / name
        if not checkpoint_file.is_file():
            raise FileNotFoundError(f"checkpoint tokenizer file is missing: {checkpoint_file}")
        if not base_file.is_file():
            raise FileNotFoundError(f"base tokenizer file is missing: {base_file}")
        checkpoint_hash = sha256(checkpoint_file)
        if checkpoint_hash != sha256(base_file):
            raise RuntimeError(f"checkpoint tokenizer differs from base tokenizer: {name}")
        hashes[name] = checkpoint_hash

    checkpoint_config = json.loads((checkpoint / "tokenizer_config.json").read_text())
    base_config = json.loads((base_model / "tokenizer_config.json").read_text())
    semantic_fields = (
        "add_prefix_space",
        "bos_token",
        "clean_up_tokenization_spaces",
        "eos_token",
        "model_input_names",
        "model_max_length",
        "pad_token",
        "unk_token",
    )
    mismatches = {
        field: {"checkpoint": checkpoint_config.get(field), "base": base_config.get(field)}
        for field in semantic_fields
        if checkpoint_config.get(field) != base_config.get(field)
    }
    if mismatches:
        raise RuntimeError(f"checkpoint tokenizer config differs from base tokenizer: {mismatches}")
    return hashes


def render_inference_config(
    *,
    checkpoint: Path,
    base_model: Path,
    job_name: str,
) -> str:
    return f'''gpu_memory_utilization = 0.90
enable_fp32_lm_head = true

[model]
name = {json.dumps(str(checkpoint))}
max_model_len = 262144
tool_call_parser = "qwen3_coder"
reasoning_parser = "nemotron_v3"

[parallel]
tp = 8

[server]
port = 8000

[deployment]
type = "multi_node"
gpus_per_node = 8
num_nodes = 4
backend_port = 8100

[deployment.router]
port = 8000
policy = "consistent_hash"

[vllm_extra]
language_model_only = true
gdn_prefill_backend = "triton"
enable_prefix_caching = true
served_model_name = ["{CANONICAL_MODEL}"]
hf_config_path = {json.dumps(str(base_model))}
tokenizer = {json.dumps(str(base_model))}

[slurm]
job_name = {json.dumps(job_name)}
project_dir = {json.dumps(str(PROJECT_DIR))}
partition = "h200"
account = "ram"
time = "120:00:00"
template_path = {json.dumps(str(INFERENCE_TEMPLATE))}
sync_environment = false
pre_run_command = "export HF_HOME=/checkpoint/ram-h100-2/tianhaowu/.cache/huggingface; export HF_HUB_CACHE=$HF_HOME/hub; export HF_HUB_OFFLINE=1"
'''


def render_eval_config(*, name: str, inference_job_id: int) -> str:
    return f'''name = {json.dumps(name)}
provider = "vmvm"
inference_job_id = {inference_job_id}
model = "{CANONICAL_MODEL}"
tasks_path = "{TASKS_PATH}"
n_attempts = 1
n_concurrent = 32
max_retries = 6
verifier_timeout_multiplier = 4.0
sandbox_timeout_sec = 14400
sandbox_startup_timeout_sec = 3600

[mini_swe]
step_limit = 200
timeout_sec = 10800

[sampling]
max_tokens = 32768
temperature = 1.0
top_p = 0.95
top_k = 20

[thinking]
enabled = true
preserve_previous = true
'''


def launch_environment() -> dict[str, str]:
    env = os.environ.copy()
    scheduler_prefixes = ("SBATCH_", "SLURM_", "SRUN_", "PMIX_")
    for name in tuple(env):
        if name.startswith(scheduler_prefixes):
            env.pop(name)
    env["UV_PROJECT_ENVIRONMENT"] = INFERENCE_ENV
    return env


def submit_sbatch(args: list[str], *, env: dict[str, str]) -> int:
    output = command(["sbatch", "--parsable", *args], env=env)
    return int(output.split(";", maxsplit=1)[0])


def find_job_id(job_name: str) -> int | None:
    matches = set()
    queued = subprocess.run(
        ["squeue", "-h", "-u", os.environ["USER"], "-n", job_name, "-o", "%A|%j"],
        check=False,
        capture_output=True,
        text=True,
    )
    if queued.returncode == 0:
        for line in queued.stdout.splitlines():
            job_id, found_name = line.split("|", maxsplit=1)
            if found_name == job_name and job_id.isdigit():
                matches.add(int(job_id))
    start_time = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    accounted = command(
        [
            "sacct",
            "-X",
            "-n",
            "-P",
            "--name",
            job_name,
            "--starttime",
            start_time,
            "--format=JobIDRaw,JobName%128",
        ]
    )
    for line in accounted.splitlines():
        job_id, found_name = line.split("|", maxsplit=1)
        if found_name == job_name and job_id.isdigit():
            matches.add(int(job_id))
    if len(matches) > 1:
        raise RuntimeError(f"multiple scheduler jobs match {job_name}: {sorted(matches)}")
    return next(iter(matches), None)


def launch_eval(
    spec: RunSpec,
    run_state: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    state_dir: Path,
    generation: int,
) -> None:
    best = run_state["best_checkpoint"]
    step = best["step"]
    launches = run_state.setdefault("launches", {})
    previous_launch = run_state.get("launch")
    if previous_launch is not None and "1" not in launches:
        launches["1"] = previous_launch
    launch = launches.setdefault(str(generation), {})
    launch["generation"] = generation
    run_state["launch"] = launch
    suffix = "" if generation == 1 else f"-r{generation}"
    launch_root = state_dir / "launches" / f"{spec.label}-step-{step}{suffix}"
    launch_root.mkdir(parents=True, exist_ok=True)
    checkpoint = Path(best["preserved_path"])
    base_model = Path(run_state["config"]["base_model_path"])

    tokenizer_hashes = verify_tokenizer(checkpoint, base_model)
    launch["tokenizer_sha256"] = tokenizer_hashes
    inference_name = f"nemotron-best-{spec.job_id}-s{step}-infer{suffix}"
    inference_config = launch_root / "inference.toml"
    inference_config.write_text(
        render_inference_config(checkpoint=checkpoint, base_model=base_model, job_name=inference_name)
    )
    deployment_dir = launch_root / "inference"
    env = launch_environment()

    if "inference_job_id" not in launch:
        command(
            [
                "uv",
                "run",
                "--no-sync",
                "inference",
                "@",
                str(inference_config),
                "--output-dir",
                str(deployment_dir),
                "--dry-run",
            ],
            env=env,
        )
        inference_sbatch = deployment_dir / "inference.sbatch"
        if not inference_sbatch.is_file():
            raise FileNotFoundError(f"inference dry-run did not create {inference_sbatch}")
        launch["inference_config"] = str(inference_config)
        launch["inference_output_dir"] = str(deployment_dir)
        launch["inference_job_name"] = inference_name
        launch["inference_submission_intent_at"] = now()
        atomic_write_json(state_path, state)
        launch["inference_job_id"] = find_job_id(inference_name) or submit_sbatch([str(inference_sbatch)], env=env)
        launch["inference_submitted_at"] = now()
        atomic_write_json(state_path, state)

    eval_name = f"nemotron-super-deepswe-{spec.label}-best-s{step}{suffix}"
    eval_job_name = f"deepswe-{spec.label}-{spec.job_id}-s{step}{suffix}"
    eval_config = launch_root / "deepswe_vmvm.toml"
    eval_config.write_text(render_eval_config(name=eval_name, inference_job_id=launch["inference_job_id"]))
    if "eval_job_id" not in launch:
        launch["eval_config"] = str(eval_config)
        launch["eval_job_name"] = eval_job_name
        launch["eval_submission_intent_at"] = now()
        atomic_write_json(state_path, state)
        launch["eval_job_id"] = find_job_id(eval_job_name) or submit_sbatch(
            [
                f"--dependency=after:{launch['inference_job_id']}",
                f"--job-name={eval_job_name}",
                str(EVAL_SBATCH),
                str(eval_config),
            ],
            env=env,
        )
        launch["eval_submitted_at"] = now()
        atomic_write_json(state_path, state)

    if "cleanup_job_id" not in launch:
        cleanup_job_name = f"cleanup-{spec.job_id}-s{step}{suffix}"
        launch["cleanup_job_name"] = cleanup_job_name
        launch["cleanup_submission_intent_at"] = now()
        atomic_write_json(state_path, state)
        launch["cleanup_job_id"] = find_job_id(cleanup_job_name) or submit_sbatch(
            [
                f"--dependency=afterany:{launch['eval_job_id']}",
                f"--job-name={cleanup_job_name}",
                "--partition=cpu",
                "--qos=cpu_lowest",
                "--account=ram",
                "--time=00:10:00",
                f"--wrap=scancel {launch['inference_job_id']}",
            ],
            env=env,
        )
        launch["cleanup_submitted_at"] = now()
        atomic_write_json(state_path, state)


def append_status(spec: RunSpec, run_state: dict[str, Any], message: str) -> None:
    latest = run_state.get("latest_train") or {}
    best = run_state.get("best_checkpoint") or {}
    lines = [
        "",
        f"## {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"**Step**: {latest.get('step', '-')} / {run_state['config']['max_steps']}",
        f"**Health**: {run_state['scheduler']['state']}",
        "",
        (
            f"**Progress**: Latest validation={run_state.get('latest_validation')}; "
            f"best preserved checkpoint=step {best.get('step', '-')} loss {best.get('loss', '-')}."
        ),
        f"**Notes**: {message}",
    ]
    with (spec.run_dir / "STATUS.md").open("a") as file:
        file.write("\n".join(lines) + "\n")


def initialize_state(specs: list[RunSpec], state_path: Path) -> dict[str, Any]:
    if state_path.is_file():
        state = json.loads(state_path.read_text())
        expected = {spec.label: {"job_id": spec.job_id, "run_dir": str(spec.run_dir)} for spec in specs}
        actual = {label: {"job_id": row["job_id"], "run_dir": row["run_dir"]} for label, row in state["runs"].items()}
        if actual != expected:
            raise ValueError("existing watcher state does not match requested runs")
        return state
    state = {
        "schema_version": 1,
        "created_at": now(),
        "status": "monitoring",
        "runs": {
            spec.label: {
                "job_id": spec.job_id,
                "run_dir": str(spec.run_dir),
                "config": load_run_config(spec),
            }
            for spec in specs
        },
    }
    atomic_write_json(state_path, state)
    return state


def collect_run(spec: RunSpec, run_state: dict[str, Any]) -> bool:
    previous_state = run_state.get("scheduler", {}).get("state")
    previous_validation_count = len(run_state.get("validations", []))
    scheduler = scheduler_status(spec.job_id)
    log = parse_trainer_log(spec)
    stable_steps = stable_checkpoint_steps(spec)
    validations = log["validations"]
    preserve_manifest = spec.run_dir / "best_val_weights/best.json"
    if "best_checkpoint" not in run_state and preserve_manifest.is_file():
        run_state["best_checkpoint"] = json.loads(preserve_manifest.read_text())
    candidates = [item for item in validations if item["step"] > 0]
    if candidates:
        best_candidate = min(candidates, key=lambda item: (item["loss"], item["step"]))
        run_state["pending_best_validation"] = best_candidate
        if best_candidate["step"] in stable_steps:
            run_state["best_checkpoint"] = preserve_best_checkpoint(spec, best_candidate)

    run_state.update(
        scheduler=scheduler,
        latest_train=log["latest_train"],
        validations=validations,
        latest_validation=validations[-1] if validations else None,
        fatal_matches=log["fatal_matches"],
        finished_marker=log["finished_marker"],
        stable_checkpoint_steps=stable_steps,
        updated_at=now(),
    )
    changed = previous_state != scheduler["state"] or previous_validation_count != len(validations)
    if changed:
        append_status(
            spec,
            run_state,
            "Best-validation watcher is preserving stable checkpoints for the VMVM DeepSWE handoff.",
        )

    if scheduler["state"] in ACTIVE_STATES:
        return False
    if scheduler["state"] != "COMPLETED" or scheduler["exit_code"] != "0:0":
        raise RuntimeError(f"training job {spec.job_id} ended as {scheduler['state']} ({scheduler['exit_code']})")
    if scheduler["restarts"] != 0:
        raise RuntimeError(f"training job {spec.job_id} completed with {scheduler['restarts']} restarts")
    if not log["finished_marker"]:
        raise RuntimeError(f"training job {spec.job_id} lacks the SFT completion marker")
    max_steps = run_state["config"]["max_steps"]
    if not validations or validations[-1]["step"] != max_steps:
        raise RuntimeError(f"training job {spec.job_id} lacks final validation at step {max_steps}")
    if max_steps not in stable_steps:
        raise RuntimeError(f"training job {spec.job_id} lacks final stable weights at step {max_steps}")
    expected_best = min(
        (item for item in validations if item["step"] > 0),
        key=lambda item: (item["loss"], item["step"]),
    )
    best = run_state.get("best_checkpoint")
    if best is None or best["step"] != expected_best["step"] or best["loss"] != expected_best["loss"]:
        raise RuntimeError(f"best checkpoint preservation mismatch for training job {spec.job_id}")
    return True


def main() -> None:
    args = parse_args()
    if args.poll_seconds <= 0:
        raise ValueError("poll-seconds must be positive")
    if args.launch_generation <= 0:
        raise ValueError("launch-generation must be positive")
    specs = args.run
    if len({spec.label for spec in specs}) != len(specs):
        raise ValueError("run labels must be unique")
    state_dir = args.state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "status.json"
    state = initialize_state(specs, state_path)

    while True:
        try:
            terminal = []
            for spec in specs:
                terminal.append(collect_run(spec, state["runs"][spec.label]))
            state["updated_at"] = now()
            state["status"] = "ready_to_launch" if all(terminal) else "monitoring"
            if all(terminal):
                state.pop("error", None)
                state.pop("last_transient_error", None)
            atomic_write_json(state_path, state)
            summary = {
                label: {
                    "state": row["scheduler"]["state"],
                    "step": (row.get("latest_train") or {}).get("step"),
                    "latest_validation": row.get("latest_validation"),
                    "best": row.get("best_checkpoint"),
                }
                for label, row in state["runs"].items()
            }
            print(json.dumps(summary, sort_keys=True), flush=True)
            if all(terminal):
                if args.launch:
                    for spec in specs:
                        launch_eval(
                            spec,
                            state["runs"][spec.label],
                            state,
                            state_path,
                            state_dir,
                            args.launch_generation,
                        )
                    state["status"] = "launched"
                    state["launch_generation"] = args.launch_generation
                    state["launched_at"] = now()
                    atomic_write_json(state_path, state)
                return
            if args.once:
                return
            time.sleep(args.poll_seconds)
        except (OSError, subprocess.CalledProcessError) as error:
            state["updated_at"] = now()
            state["last_transient_error"] = repr(error)
            atomic_write_json(state_path, state)
            if args.once:
                raise
            print(f"Transient watcher error: {error}", flush=True)
            time.sleep(args.poll_seconds)
        except RuntimeError as error:
            state["updated_at"] = now()
            state["status"] = "blocked"
            state["error"] = str(error)
            atomic_write_json(state_path, state)
            raise


if __name__ == "__main__":
    main()
