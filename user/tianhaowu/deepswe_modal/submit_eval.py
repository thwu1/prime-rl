import argparse
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

PROJECT_DIR = Path("/storage/home/tianhaowu/prime-rl")
DRIVER = PROJECT_DIR / "user/tianhaowu/deepswe_modal/run_deepswe_modal.py"
GENERATED_CONFIG_DIR = Path("/checkpoint/ram/tianhaowu/deepswe_eval/configs")
DEFAULT_MODEL = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"
DEFAULT_TASKS = Path("/checkpoint/ram/tianhaowu/deepswe_eval/deep-swe/tasks")
DEFAULT_JOBS_DIR = Path("/checkpoint/ram/tianhaowu/deepswe_eval/jobs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def number(value: object, name: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    return value


def load_toml(path: Path) -> dict:
    with path.open("rb") as file:
        return tomllib.load(file)


def build_configs(source: dict) -> tuple[dict, dict]:
    name = source.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError("name must contain only letters, numbers, '.', '_', or '-'")

    inference_job_id = source.get("inference_job_id")
    if not isinstance(inference_job_id, (str, int)) or isinstance(inference_job_id, bool):
        raise ValueError("inference_job_id must be a SLURM job ID")
    inference_job_id = str(inference_job_id)

    model = source.get("model", DEFAULT_MODEL)
    if not isinstance(model, str) or not model:
        raise ValueError("model must be a non-empty string")

    tasks_path = Path(source.get("tasks_path", DEFAULT_TASKS))
    if not tasks_path.is_dir():
        raise FileNotFoundError(f"DeepSWE tasks directory does not exist: {tasks_path}")

    n_attempts = positive_int(source.get("n_attempts", 1), "n_attempts")
    n_concurrent = positive_int(source.get("n_concurrent", 16), "n_concurrent")
    max_retries = positive_int(source.get("max_retries", 1), "max_retries")

    thinking = source.get("thinking", {})
    if not isinstance(thinking, dict):
        raise ValueError("thinking must be a TOML table")
    if thinking.get("enabled", True) is not True:
        raise ValueError("Nemotron DeepSWE evals require thinking.enabled = true")
    if thinking.get("preserve_previous", True) is not True:
        raise ValueError(
            "Nemotron DeepSWE evals require thinking.preserve_previous = true"
        )

    sampling = source.get("sampling", {})
    if not isinstance(sampling, dict):
        raise ValueError("sampling must be a TOML table")
    max_tokens = positive_int(sampling.get("max_tokens", 32768), "sampling.max_tokens")
    temperature = number(sampling.get("temperature", 1.0), "sampling.temperature")
    top_p = number(sampling.get("top_p", 0.95), "sampling.top_p")
    top_k = positive_int(sampling.get("top_k", 20), "sampling.top_k")
    if not 0 <= top_p <= 1:
        raise ValueError("sampling.top_p must be between 0 and 1")
    if temperature < 0:
        raise ValueError("sampling.temperature must be non-negative")

    mini_swe_version = source.get("mini_swe_version", "2.2.8")
    if not isinstance(mini_swe_version, str) or not mini_swe_version:
        raise ValueError("mini_swe_version must be a non-empty string")

    dataset = {"path": str(tasks_path)}
    if "n_tasks" in source:
        dataset["n_tasks"] = positive_int(source["n_tasks"], "n_tasks")
    if "sample_seed" in source:
        if not isinstance(source["sample_seed"], int) or isinstance(source["sample_seed"], bool):
            raise ValueError("sample_seed must be an integer")
        dataset["sample_seed"] = source["sample_seed"]

    pier_config = {
        "job_name": name,
        "jobs_dir": str(DEFAULT_JOBS_DIR),
        "n_attempts": n_attempts,
        "n_concurrent_trials": n_concurrent,
        "quiet": True,
        "retry": {"max_retries": max_retries},
        "environment": {
            "type": "modal",
            "delete": True,
            "kwargs": {
                "app_name": "__pier_deepswe__",
                "sandbox_timeout_secs": 86400,
            },
        },
        "agents": [
            {
                "name": "mini-swe-agent",
                "model_name": f"openai/{model}",
                "env": {
                    "OPENAI_API_KEY": "${OPENAI_API_KEY}",
                    "OPENAI_BASE_URL": "${OPENAI_BASE_URL}",
                },
                "kwargs": {
                    "version": mini_swe_version,
                    "cost_limit": 0,
                    "model_class": "litellm",
                    "model_kwargs": {
                        "custom_llm_provider": "openai",
                        "drop_params": True,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "top_p": top_p,
                        "extra_body": {
                            "top_k": top_k,
                            "chat_template_kwargs": {
                                "enable_thinking": True,
                                "truncate_history_thinking": False,
                            },
                        },
                    },
                },
            }
        ],
        "datasets": [dataset],
    }
    runtime = {
        "name": name,
        "inference_job_id": inference_job_id,
        "model": model,
        "mini_swe_version": mini_swe_version,
    }
    return pier_config, runtime


def main() -> None:
    args = parse_args()
    pier_config, runtime = build_configs(load_toml(args.config.resolve()))
    slurm_job_id = os.environ.get("SLURM_JOB_ID", "dry-run")
    GENERATED_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    generated_config = GENERATED_CONFIG_DIR / f"{runtime['name']}-{slurm_job_id}.json"
    generated_config.write_text(json.dumps(pier_config, indent=2))

    job_name = f"{runtime['name']}-{slurm_job_id}"
    command = [
        "uv",
        "run",
        "--no-sync",
        "python",
        str(DRIVER),
        str(generated_config),
        "--inference-job-id",
        runtime["inference_job_id"],
        "--job-name",
        job_name,
        "--model-name",
        runtime["model"],
        "--mini-swe-version",
        runtime["mini_swe_version"],
    ]
    print(f"Generated Pier config: {generated_config}", flush=True)
    print(f"Eval job name: {job_name}", flush=True)
    if args.dry_run:
        print("Command: " + " ".join(command), flush=True)
        return
    subprocess.run(command, cwd=PROJECT_DIR, check=True)


if __name__ == "__main__":
    main()
