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
DEEPSWE_ENVIRONMENT_BUILD_TIMEOUT_SEC = 1800
PIER_AGENT_SETUP_TIMEOUT_SEC = 360
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
    parser.add_argument("--resume-job-id", type=int)
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


def positive_number(value: object, name: str) -> int | float:
    value = number(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
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
    session_timeout: int = 7200,
) -> dict:
    if provider == "modal":
        return {
            "type": "modal",
            "delete": True,
            "kwargs": {
                "app_name": modal_app_name,
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
        else {
            "mode": "oci-runner",
            "session_timeout": session_timeout,
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

    model = source.get("model", DEFAULT_MODEL)
    if not isinstance(model, str) or not model:
        raise ValueError("model must be a non-empty string")

    inference_job_id = source.get("inference_job_id")
    upstream_info_value = source.get("upstream_info_path")
    if (inference_job_id is None) == (upstream_info_value is None):
        raise ValueError("set exactly one of inference_job_id or upstream_info_path")
    upstream_info_path = None
    render_endpoints_path = None
    if inference_job_id is not None:
        if not isinstance(inference_job_id, (str, int)) or isinstance(inference_job_id, bool):
            raise ValueError("inference_job_id must be a SLURM job ID")
        inference_job_id = str(inference_job_id)
    else:
        upstream_info_path = Path(upstream_info_value).resolve()
        if not upstream_info_path.is_file():
            raise FileNotFoundError(f"upstream info does not exist: {upstream_info_path}")
        upstream_info = json.loads(upstream_info_path.read_text())
        if not isinstance(upstream_info, dict):
            raise TypeError("upstream_info_path must contain a JSON object")
        if upstream_info.get("model") != model:
            raise ValueError(f"upstream model is {upstream_info.get('model')!r}, expected {model!r}")
        render_endpoints_path = Path(
            source.get("render_endpoints_path", upstream_info_path.parent / "endpoints")
        ).resolve()
        if not render_endpoints_path.is_dir():
            raise FileNotFoundError(f"render endpoints directory does not exist: {render_endpoints_path}")

    upstream_session_header = source.get("upstream_session_header")
    if upstream_session_header is not None and (
        not isinstance(upstream_session_header, str) or not re.fullmatch(r"[A-Za-z0-9-]+", upstream_session_header)
    ):
        raise ValueError("upstream_session_header must be an HTTP header name")

    tasks_path = Path(source.get("tasks_path", DEFAULT_TASKS))
    if not tasks_path.is_dir():
        raise FileNotFoundError(f"DeepSWE tasks directory does not exist: {tasks_path}")

    n_attempts = positive_int(source.get("n_attempts", 1), "n_attempts")
    n_concurrent = positive_int(source.get("n_concurrent", 32), "n_concurrent")
    max_retries = positive_int(source.get("max_retries", 1), "max_retries")
    verifier_timeout_multiplier = positive_number(
        source.get("verifier_timeout_multiplier", 1.0),
        "verifier_timeout_multiplier",
    )

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
        raise ValueError("DeepSWE evals require thinking.enabled = true")
    preserve_previous = thinking.get("preserve_previous", True)
    if not isinstance(preserve_previous, bool):
        raise ValueError("thinking.preserve_previous must be a boolean")
    truncate_history_thinking = not preserve_previous
    chat_template_kwargs = thinking.get("template_kwargs")
    if chat_template_kwargs is None:
        chat_template_kwargs = {
            "enable_thinking": True,
            "truncate_history_thinking": truncate_history_thinking,
        }
    if not isinstance(chat_template_kwargs, dict):
        raise ValueError("thinking.template_kwargs must be a TOML table")
    json.dumps(chat_template_kwargs)

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
    agent_timeout_sec = mini_swe.get("timeout_sec")
    if agent_timeout_sec is not None:
        agent_timeout_sec = positive_int(agent_timeout_sec, "mini_swe.timeout_sec")
    sandbox_timeout_sec = positive_int(
        source.get("sandbox_timeout_sec", max(agent_timeout_sec or 0, 7200)),
        "sandbox_timeout_sec",
    )
    sandbox_startup_timeout_sec = positive_int(
        source.get("sandbox_startup_timeout_sec", 3600),
        "sandbox_startup_timeout_sec",
    )
    if agent_timeout_sec is not None and sandbox_timeout_sec < agent_timeout_sec:
        raise ValueError("sandbox_timeout_sec must be greater than or equal to mini_swe.timeout_sec")

    dataset = {"path": str(tasks_path)}
    if "task_names" in source:
        task_names = source["task_names"]
        if not isinstance(task_names, list) or not task_names:
            raise ValueError("task_names must be a non-empty array")
        if any(not isinstance(task_name, str) or not task_name for task_name in task_names):
            raise ValueError("task_names entries must be non-empty strings")
        if len(task_names) != len(set(task_names)):
            raise ValueError("task_names entries must be unique")
        missing_tasks = [task_name for task_name in task_names if not (tasks_path / task_name).is_dir()]
        if missing_tasks:
            raise FileNotFoundError(f"DeepSWE task directories do not exist: {missing_tasks}")
        dataset["task_names"] = task_names
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
        session_timeout=sandbox_timeout_sec,
    )
    model_kwargs = {
        "custom_llm_provider": "openai",
        "drop_params": True,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "extra_body": {
            "top_k": top_k,
            "chat_template_kwargs": chat_template_kwargs,
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

    agent_config = {
        "import_path": DEEPSWE_AGENT_IMPORT,
        "model_name": f"openai/{model}",
        "env": {
            "OPENAI_API_KEY": "${OPENAI_API_KEY}",
            "OPENAI_BASE_URL": "${OPENAI_BASE_URL}",
        },
        "kwargs": agent_kwargs,
    }
    if agent_timeout_sec is not None:
        agent_config["override_timeout_sec"] = agent_timeout_sec

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
        "environment": environment,
        "agents": [agent_config],
        "datasets": [dataset],
    }
    runtime = {
        "name": name,
        "inference_job_id": inference_job_id,
        "upstream_info_path": str(upstream_info_path) if upstream_info_path is not None else None,
        "render_endpoints_path": (str(render_endpoints_path) if render_endpoints_path is not None else None),
        "upstream_session_header": upstream_session_header,
        "model": model,
        "mini_swe_version": mini_swe_version,
        "provider": provider,
        "sandbox_startup_timeout_sec": sandbox_startup_timeout_sec,
        "sandbox_timeout_sec": sandbox_timeout_sec,
        "chat_template_kwargs": chat_template_kwargs,
        "truncate_history_thinking": truncate_history_thinking,
        "verifier_timeout_multiplier": verifier_timeout_multiplier,
    }
    return pier_config, runtime


def main() -> None:
    args = parse_args()
    pier_config, runtime = build_configs(
        load_toml(args.config.resolve()),
        provider_override=args.provider,
    )
    slurm_job_id = os.environ.get("SLURM_JOB_ID", "dry-run")
    source_job_id = str(args.resume_job_id) if args.resume_job_id is not None else slurm_job_id
    gateway_model_name = f"deepswe-{runtime['provider']}-{source_job_id}"
    pier_config["agents"][0]["model_name"] = f"openai/{gateway_model_name}"
    run_name = f"{runtime['name']}-{runtime['provider']}"
    job_name = f"{run_name}-{source_job_id}"
    if args.resume_job_id is None:
        GENERATED_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        generated_config = GENERATED_CONFIG_DIR / f"{job_name}.json"
        generated_config.write_text(json.dumps(pier_config, indent=2))
        config_message = f"Generated Pier config: {generated_config}"
    else:
        job_dir = DEFAULT_JOBS_DIR / job_name
        generated_config = job_dir / "config.json"
        result_path = job_dir / "result.json"
        if not generated_config.is_file() or not result_path.is_file():
            raise FileNotFoundError(f"Pier job is not resumable: {job_dir}")
        result = json.loads(result_path.read_text())
        if result.get("finished_at") is not None:
            raise ValueError(f"Pier job is already terminal: {job_dir}")
        queue_result = subprocess.run(
            ["squeue", "-h", "-j", source_job_id, "-o", "%T"],
            check=False,
            text=True,
            capture_output=True,
        )
        if queue_result.returncode != 0 and "Invalid job id specified" not in queue_result.stderr:
            queue_result.check_returncode()
        active_state = queue_result.stdout.strip()
        if active_state:
            raise RuntimeError(f"refusing to resume while Slurm job {source_job_id} is active: {active_state}")
        saved_config = json.loads(generated_config.read_text())
        saved_model_name = saved_config["agents"][0]["model_name"]
        expected_model_name = f"openai/{gateway_model_name}"
        if saved_model_name != expected_model_name:
            raise ValueError(f"saved agent model is {saved_model_name!r}, expected {expected_model_name!r}")
        config_message = f"Resuming Pier config: {generated_config}"
    command = [
        "uv",
        "run",
        "--no-sync",
        "python",
        str(DRIVER),
        str(generated_config),
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
        "--sandbox-startup-timeout-sec",
        str(runtime["sandbox_startup_timeout_sec"]),
        "--chat-template-kwargs-json",
        json.dumps(runtime["chat_template_kwargs"], separators=(",", ":")),
    ]
    if runtime["inference_job_id"] is not None:
        command.extend(["--inference-job-id", runtime["inference_job_id"]])
    else:
        command.extend(["--upstream-info-path", runtime["upstream_info_path"]])
        command.extend(["--render-endpoints-path", runtime["render_endpoints_path"]])
    if runtime["upstream_session_header"] is not None:
        command.extend(["--upstream-session-header", runtime["upstream_session_header"]])
    if runtime["truncate_history_thinking"]:
        command.append("--truncate-history-thinking")
    print(config_message, flush=True)
    print(f"Eval job name: {job_name}", flush=True)
    if args.dry_run:
        print("Command: " + " ".join(command), flush=True)
        return
    subprocess.run(command, cwd=PROJECT_DIR, check=True)


if __name__ == "__main__":
    main()
