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
MINI_SWE_INSTANCE_TEMPLATE = PROJECT_DIR / ("user/tianhaowu/deepswe_modal/mini_swe_instance_template.txt")
PIER_RUNTIME_IMPORT = "user.tianhaowu.deepswe_sandbox.pier_runtime:PierRuntimeEnvironment"
DEEPSWE_AGENT_IMPORT = "user.tianhaowu.deepswe_sandbox.pier_agent:DeepSweMiniSweAgent"
PROVIDERS = {"modal", "vmvm", "sandoq"}
INFRA_RETRY_EXCEPTIONS = [
    "AgentSetupTimeoutError",
    "EnvironmentStartTimeoutError",
    "SandboxError",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--provider", choices=sorted(PROVIDERS))
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


def mini_swe_config(step_limit: int | None) -> str:
    template = MINI_SWE_INSTANCE_TEMPLATE.read_text().rstrip()
    lines = ["agent:", "  instance_template: |"]
    lines.extend(f"    {line}" for line in template.splitlines())
    if step_limit is not None:
        lines.append("  agent_class: default")
        lines.append(f"  step_limit: {step_limit}")
    return "\n".join(lines) + "\n"


def build_environment(
    provider: str,
    provider_options: dict,
    *,
    modal_app_name: str,
) -> dict:
    if provider == "modal":
        return {
            "type": "modal",
            "delete": True,
            "kwargs": {
                "app_name": modal_app_name,
                "sandbox_timeout_secs": 86400,
                **provider_options,
            },
        }
    defaults = (
        {
            "session_timeout": 7200,
            "lease_ttl": "60s",
            "max_session_buffer_size": 16 * 1024 * 1024,
        }
        if provider == "vmvm"
        else {
            "mode": "oci-runner",
            "session_timeout": 7200,
            "host_tunnel": "modal",
        }
    )
    return {
        "import_path": PIER_RUNTIME_IMPORT,
        "delete": True,
        "kwargs": {
            "provider": provider,
            "runtime_options": {**defaults, **provider_options},
        },
    }


def build_configs(
    source: dict,
    provider_override: str | None = None,
) -> tuple[dict, dict]:
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
    n_concurrent = positive_int(source.get("n_concurrent", 32), "n_concurrent")
    max_retries = positive_int(source.get("max_retries", 1), "max_retries")

    provider = provider_override or source.get("provider", "modal")
    if provider not in PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(PROVIDERS)}")
    provider_options = source.get("provider_options", {})
    if not isinstance(provider_options, dict):
        raise ValueError("provider_options must be a TOML table")

    thinking = source.get("thinking", {})
    if not isinstance(thinking, dict):
        raise ValueError("thinking must be a TOML table")
    if thinking.get("enabled", True) is not True:
        raise ValueError("Nemotron DeepSWE evals require thinking.enabled = true")
    if thinking.get("preserve_previous", True) is not True:
        raise ValueError("Nemotron DeepSWE evals require thinking.preserve_previous = true")

    sampling = source.get("sampling", {})
    if not isinstance(sampling, dict):
        raise ValueError("sampling must be a TOML table")
    max_tokens = positive_int(sampling.get("max_tokens", 32768), "sampling.max_tokens")
    temperature = number(sampling.get("temperature", 1.0), "sampling.temperature")
    top_p = number(sampling.get("top_p", 0.95), "sampling.top_p")
    top_k = positive_int(sampling.get("top_k", 20), "sampling.top_k")
    seed = sampling.get("seed")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool) or seed < 0):
        raise ValueError("sampling.seed must be a non-negative integer")
    if not 0 <= top_p <= 1:
        raise ValueError("sampling.top_p must be between 0 and 1")
    if temperature < 0:
        raise ValueError("sampling.temperature must be non-negative")

    mini_swe_version = source.get("mini_swe_version", "2.2.8")
    if not isinstance(mini_swe_version, str) or not mini_swe_version:
        raise ValueError("mini_swe_version must be a non-empty string")
    mini_swe = source.get("mini_swe", {})
    if not isinstance(mini_swe, dict):
        raise ValueError("mini_swe must be a TOML table")
    step_limit = mini_swe.get("step_limit")
    if step_limit is not None:
        step_limit = positive_int(step_limit, "mini_swe.step_limit")

    dataset = {"path": str(tasks_path)}
    if "n_tasks" in source:
        dataset["n_tasks"] = positive_int(source["n_tasks"], "n_tasks")
    if "sample_seed" in source:
        if not isinstance(source["sample_seed"], int) or isinstance(source["sample_seed"], bool):
            raise ValueError("sample_seed must be an integer")
        dataset["sample_seed"] = source["sample_seed"]

    environment = build_environment(
        provider,
        provider_options,
        modal_app_name="__pier_deepswe__",
    )
    model_kwargs = {
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
    }
    if seed is not None:
        model_kwargs["seed"] = seed
    agent_kwargs = {
        "version": mini_swe_version,
        "cost_limit": 0,
        "model_class": "litellm",
        "model_kwargs": model_kwargs,
        "config_yaml": mini_swe_config(step_limit),
    }

    pier_config = {
        "job_name": name,
        "jobs_dir": str(DEFAULT_JOBS_DIR),
        "n_attempts": n_attempts,
        "n_concurrent_trials": n_concurrent,
        "quiet": True,
        "retry": {
            "max_retries": max_retries,
            "include_exceptions": INFRA_RETRY_EXCEPTIONS,
        },
        "environment": environment,
        "agents": [
            {
                "import_path": DEEPSWE_AGENT_IMPORT,
                "model_name": f"openai/{model}",
                "env": {
                    "OPENAI_API_KEY": "${OPENAI_API_KEY}",
                    "OPENAI_BASE_URL": "${OPENAI_BASE_URL}",
                },
                "kwargs": agent_kwargs,
            }
        ],
        "datasets": [dataset],
    }
    runtime = {
        "name": name,
        "inference_job_id": inference_job_id,
        "model": model,
        "mini_swe_version": mini_swe_version,
        "provider": provider,
    }
    return pier_config, runtime


def main() -> None:
    args = parse_args()
    pier_config, runtime = build_configs(
        load_toml(args.config.resolve()),
        provider_override=args.provider,
    )
    slurm_job_id = os.environ.get("SLURM_JOB_ID", "dry-run")
    gateway_model_name = f"deepswe-{runtime['provider']}-{slurm_job_id}"
    pier_config["agents"][0]["model_name"] = f"openai/{gateway_model_name}"
    GENERATED_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    run_name = f"{runtime['name']}-{runtime['provider']}"
    generated_config = GENERATED_CONFIG_DIR / f"{run_name}-{slurm_job_id}.json"
    generated_config.write_text(json.dumps(pier_config, indent=2))

    job_name = f"{run_name}-{slurm_job_id}"
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
        "--gateway-model-name",
        gateway_model_name,
        "--mini-swe-version",
        runtime["mini_swe_version"],
        "--provider",
        runtime["provider"],
    ]
    print(f"Generated Pier config: {generated_config}", flush=True)
    print(f"Eval job name: {job_name}", flush=True)
    if args.dry_run:
        print("Command: " + " ".join(command), flush=True)
        return
    subprocess.run(command, cwd=PROJECT_DIR, check=True)


if __name__ == "__main__":
    main()
