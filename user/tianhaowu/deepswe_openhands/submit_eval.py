import argparse
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

PROJECT_DIR = Path("/storage/home/tianhaowu/prime-rl")
DRIVER = PROJECT_DIR / "user/tianhaowu/deepswe_openhands/run_deepswe_openhands.py"
PROMPT_TEMPLATE = PROJECT_DIR / "user/tianhaowu/deepswe_openhands/instance_template.txt"
GENERATED_CONFIG_DIR = Path("/checkpoint/ram/tianhaowu/deepswe_eval/openhands-configs")
DEFAULT_MODEL = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"
DEFAULT_TASKS = Path("/checkpoint/ram/tianhaowu/deepswe_eval/deep-swe/tasks")
DEFAULT_JOBS_DIR = Path("/checkpoint/ram/tianhaowu/deepswe_eval/jobs")
DEEPSWE_ENVIRONMENT_BUILD_TIMEOUT_SEC = 1800
PIER_AGENT_SETUP_TIMEOUT_SEC = 360
PIER_RUNTIME_IMPORT = "user.tianhaowu.deepswe_sandbox.pier_runtime:PierRuntimeEnvironment"
OPENHANDS_AGENT_IMPORT = "user.tianhaowu.deepswe_openhands.pier_agent:DeepSweOpenHandsAgent"
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


def nonnegative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def number(value: object, name: str) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    return value


def positive_number(value: object, name: str) -> int | float:
    value = number(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def load_toml(path: Path) -> dict:
    with path.open("rb") as file:
        return tomllib.load(file)


def build_environment(
    provider: str,
    provider_options: dict,
    *,
    session_timeout: int,
) -> dict:
    if provider == "modal":
        return {
            "type": "modal",
            "delete": True,
            "kwargs": {
                "app_name": "__pier_deepswe_openhands__",
                "sandbox_timeout_secs": session_timeout,
                **provider_options,
            },
        }
    defaults = (
        {
            "session_timeout": session_timeout,
            "lease_ttl": "60s",
            "max_session_buffer_size": 16 * 1024 * 1024,
        }
        if provider == "vmvm"
        else {"mode": "oci-runner", "session_timeout": session_timeout}
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

    provider = provider_override or source.get("provider", "vmvm")
    if provider not in PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(PROVIDERS)}")
    provider_options = source.get("provider_options", {})
    if not isinstance(provider_options, dict):
        raise ValueError("provider_options must be a TOML table")

    n_attempts = positive_int(source.get("n_attempts", 1), "n_attempts")
    n_concurrent = positive_int(source.get("n_concurrent", 113), "n_concurrent")
    max_retries = positive_int(source.get("max_retries", 6), "max_retries")
    verifier_timeout_multiplier = positive_number(
        source.get("verifier_timeout_multiplier", 4.0),
        "verifier_timeout_multiplier",
    )

    thinking = source.get("thinking", {})
    if not isinstance(thinking, dict):
        raise ValueError("thinking must be a TOML table")
    if thinking.get("enabled", True) is not True:
        raise ValueError("Nemotron DeepSWE evals require thinking.enabled = true")
    preserve_previous = thinking.get("preserve_previous", True)
    if not isinstance(preserve_previous, bool):
        raise ValueError("thinking.preserve_previous must be a boolean")
    truncate_history_thinking = not preserve_previous

    sampling = source.get("sampling", {})
    if not isinstance(sampling, dict):
        raise ValueError("sampling must be a TOML table")
    max_output_tokens = positive_int(
        sampling.get("max_tokens", 32768),
        "sampling.max_tokens",
    )
    temperature = number(sampling.get("temperature", 1.0), "sampling.temperature")
    top_p = number(sampling.get("top_p", 0.95), "sampling.top_p")
    top_k = positive_int(sampling.get("top_k", 20), "sampling.top_k")
    seed = sampling.get("seed")
    if seed is not None:
        seed = nonnegative_int(seed, "sampling.seed")
    if temperature < 0:
        raise ValueError("sampling.temperature must be non-negative")
    if not 0 <= top_p <= 1:
        raise ValueError("sampling.top_p must be between 0 and 1")

    options = source.get("openhands", {})
    if not isinstance(options, dict):
        raise ValueError("openhands must be a TOML table")
    version = options.get("version", "1.42.1")
    if not isinstance(version, str) or not version:
        raise ValueError("openhands.version must be a non-empty string")
    max_iterations = positive_int(
        options.get("max_iterations", 200),
        "openhands.max_iterations",
    )
    agent_timeout_sec = positive_int(
        options.get("timeout_sec", 10800),
        "openhands.timeout_sec",
    )
    request_timeout_sec = positive_int(
        options.get("request_timeout_sec", 7200),
        "openhands.request_timeout_sec",
    )
    llm_retries = nonnegative_int(
        options.get("llm_retries", 5),
        "openhands.llm_retries",
    )
    max_input_tokens = positive_int(
        options.get("max_input_tokens", 262144),
        "openhands.max_input_tokens",
    )
    terminal_type = options.get("terminal_type", "subprocess")
    if terminal_type not in {"subprocess", "tmux"}:
        raise ValueError("openhands.terminal_type must be 'subprocess' or 'tmux'")
    terminal_no_change_timeout_sec = positive_int(
        options.get("terminal_no_change_timeout_sec", 600),
        "openhands.terminal_no_change_timeout_sec",
    )
    stuck_detection = options.get("stuck_detection", False)
    if not isinstance(stuck_detection, bool):
        raise ValueError("openhands.stuck_detection must be a boolean")

    sandbox_timeout_sec = positive_int(
        source.get("sandbox_timeout_sec", 14400),
        "sandbox_timeout_sec",
    )
    if sandbox_timeout_sec < agent_timeout_sec:
        raise ValueError("sandbox_timeout_sec must be at least openhands.timeout_sec")
    sandbox_startup_timeout_sec = positive_int(
        source.get("sandbox_startup_timeout_sec", 3600),
        "sandbox_startup_timeout_sec",
    )

    dataset: dict[str, object] = {"path": str(tasks_path)}
    if "task_names" in source:
        task_names = source["task_names"]
        if not isinstance(task_names, list) or not task_names:
            raise ValueError("task_names must be a non-empty array")
        if any(not isinstance(task, str) or not task for task in task_names):
            raise ValueError("task_names entries must be non-empty strings")
        if len(task_names) != len(set(task_names)):
            raise ValueError("task_names entries must be unique")
        missing = [task for task in task_names if not (tasks_path / task).is_dir()]
        if missing:
            raise FileNotFoundError(f"DeepSWE task directories do not exist: {missing}")
        dataset["task_names"] = task_names
    if "n_tasks" in source:
        dataset["n_tasks"] = positive_int(source["n_tasks"], "n_tasks")
    if "sample_seed" in source:
        sample_seed = source["sample_seed"]
        if not isinstance(sample_seed, int) or isinstance(sample_seed, bool):
            raise ValueError("sample_seed must be an integer")
        dataset["sample_seed"] = sample_seed

    agent_kwargs = {
        "version": version,
        "max_iterations": max_iterations,
        "stuck_detection": stuck_detection,
        "terminal_type": terminal_type,
        "terminal_no_change_timeout_sec": terminal_no_change_timeout_sec,
        "request_timeout_sec": request_timeout_sec,
        "llm_retries": llm_retries,
        "max_input_tokens": max_input_tokens,
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "seed": seed,
        "truncate_history_thinking": truncate_history_thinking,
        "prompt_template_path": str(PROMPT_TEMPLATE),
    }
    agent_config = {
        "import_path": OPENHANDS_AGENT_IMPORT,
        "model_name": f"openai/{model}",
        "env": {
            "OPENAI_API_KEY": "${OPENAI_API_KEY}",
            "OPENAI_BASE_URL": "${OPENAI_BASE_URL}",
        },
        "kwargs": agent_kwargs,
        "override_timeout_sec": agent_timeout_sec,
    }
    pier_config = {
        "job_name": name,
        "jobs_dir": str(DEFAULT_JOBS_DIR),
        "n_attempts": n_attempts,
        "n_concurrent_trials": n_concurrent,
        "agent_setup_timeout_multiplier": (sandbox_startup_timeout_sec / PIER_AGENT_SETUP_TIMEOUT_SEC),
        "environment_build_timeout_multiplier": (sandbox_startup_timeout_sec / DEEPSWE_ENVIRONMENT_BUILD_TIMEOUT_SEC),
        "verifier_timeout_multiplier": verifier_timeout_multiplier,
        "quiet": True,
        "retry": {
            "max_retries": max_retries,
            "include_exceptions": INFRA_RETRY_EXCEPTIONS,
        },
        "environment": build_environment(
            provider,
            provider_options,
            session_timeout=sandbox_timeout_sec,
        ),
        "agents": [agent_config],
        "datasets": [dataset],
    }
    runtime = {
        "name": name,
        "inference_job_id": inference_job_id,
        "model": model,
        "provider": provider,
        "sandbox_startup_timeout_sec": sandbox_startup_timeout_sec,
        "truncate_history_thinking": truncate_history_thinking,
    }
    return pier_config, runtime


def main() -> None:
    args = parse_args()
    pier_config, runtime = build_configs(
        load_toml(args.config.resolve()),
        provider_override=args.provider,
    )
    slurm_job_id = os.environ.get("SLURM_JOB_ID", "dry-run")
    gateway_model_name = f"deepswe-openhands-{runtime['provider']}-{slurm_job_id}"
    pier_config["agents"][0]["model_name"] = f"openai/{gateway_model_name}"
    GENERATED_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    run_name = f"{runtime['name']}-{runtime['provider']}"
    generated_config = GENERATED_CONFIG_DIR / f"{run_name}-{slurm_job_id}.json"
    generated_config.write_text(json.dumps(pier_config, indent=2) + "\n")

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
        "--provider",
        runtime["provider"],
        "--sandbox-startup-timeout-sec",
        str(runtime["sandbox_startup_timeout_sec"]),
    ]
    if runtime["truncate_history_thinking"]:
        command.append("--truncate-history-thinking")
    print(f"Generated Pier config: {generated_config}", flush=True)
    print(f"Eval job name: {job_name}", flush=True)
    if args.dry_run:
        print("Command: " + " ".join(command), flush=True)
        return
    subprocess.run(command, cwd=PROJECT_DIR, check=True)


if __name__ == "__main__":
    main()
