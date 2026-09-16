import tomllib
from pathlib import Path

import pytest

CONFIG_DIR = Path(__file__).parents[1] / "configs" / "eval"
EVAL_CONFIGS = sorted(CONFIG_DIR.glob("*.toml"))
FORBIDDEN_SAMPLING_FIELDS = {
    "logprobs",
    "prompt_logprobs",
    "top_logprobs",
    "return_token_ids",
}
OUTBOUND_BODY_DENYLIST = [
    "logprobs",
    "prompt_logprobs",
    "top_logprobs",
    "return_token_ids",
]


@pytest.mark.parametrize("config_path", EVAL_CONFIGS, ids=lambda path: path.name)
def test_eval_config_does_not_request_token_metadata(config_path: Path) -> None:
    config = tomllib.loads(config_path.read_text())

    assert FORBIDDEN_SAMPLING_FIELDS.isdisjoint(config.get("sampling", {}))


@pytest.mark.parametrize("config_path", EVAL_CONFIGS, ids=lambda path: path.name)
def test_eval_config_captures_model_io(config_path: Path) -> None:
    client = tomllib.loads(config_path.read_text())["client"]

    assert client["capture_model_io"] is True
    assert client["outbound_body_denylist"] == OUTBOUND_BODY_DENYLIST


@pytest.mark.parametrize(
    "filename",
    [
        "mobius_kimi_k3_max_2500.toml",
        "tb4_kimi_k3_max_miniswe.toml",
        "tb4_kimi_token_smoke.toml",
    ],
)
def test_kimi_configs_pin_harness_model_retry_policy(filename: str) -> None:
    config = tomllib.loads((CONFIG_DIR / filename).read_text())

    # EvalClient is a transparent relay, so its BaseClientConfig.max_retries
    # field is not consumed. mini-swe-agent owns provider retries instead.
    assert "max_retries" not in config["client"]
    assert config["harness"]["env"]["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] == "10"


def test_mobius_kimi_production_contract() -> None:
    config = tomllib.loads((CONFIG_DIR / "mobius_kimi_k3_max_2500.toml").read_text())

    assert config["model"] == "Kimi-K3"
    assert config["num_tasks"] == 2_500
    assert config["num_rollouts"] == 1
    assert config["max_concurrent"] == 64
    assert config["max_input_tokens"] == 262_144
    assert config["max_output_tokens"] == 262_144
    assert config["max_total_tokens"] == 262_144
    assert config["retain_traces"] is False

    client = config["client"]
    assert client["capture_model_io"] is True
    assert client["max_connections"] >= config["max_concurrent"]
    assert client["max_keepalive_connections"] >= config["max_concurrent"]
    assert client["timeout"] >= 7_200
    assert client["connect_timeout"] >= 120
    assert client["outbound_body_denylist"] == OUTBOUND_BODY_DENYLIST

    sampling = config["sampling"]
    assert sampling["reasoning_effort"] == "max"
    assert sampling["chat_template_kwargs"]["enable_thinking"] is True
    assert sampling["chat_template_kwargs"]["preserve_thinking"] is True
    assert sampling["max_tokens"] <= config["max_total_tokens"]

    taskset = config["taskset"]
    assert taskset["id"] == "terminal-bench-vmvm"
    assert taskset["dataset_revision"] == "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
    assert taskset["task_file"].endswith("/valid_tasks_2500.txt")
    assert taskset["task_file_sha256"] == (
        "d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b"
    )
    assert taskset["image_manifest"].endswith("/mobius_images.json")
    assert taskset["image_manifest_sha256"] == (
        "118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009"
    )
    assert taskset["verifier_runtime_retries"] >= 2

    runtime = config["harness"]["runtime"]
    assert runtime["type"] == "vmvm"
    assert runtime["session_timeout"] >= 43_200
    assert runtime["lease_ttl"] == "60s"

    timeouts = config["timeout"]
    assert timeouts["setup"] >= 3_600
    assert timeouts["rollout"] >= 36_000
    assert timeouts["finalize"] >= 3_600
    assert timeouts["scoring"] >= 21_600

    rollout_retries = config["retries"]["rollout"]
    assert rollout_retries["max_retries"] >= 2
    assert set(rollout_retries["include"]) == {
        "ProviderError",
        "SandboxError",
        "TunnelError",
    }


def test_eval_controller_is_cpu_only_and_supports_high_vmvm_concurrency() -> None:
    wrapper = CONFIG_DIR.parents[1] / "run_eval.sbatch"
    text = wrapper.read_text()

    assert "#SBATCH --partition=cpu_x86" in text
    assert "#SBATCH --qos=cpu_x86_lowest" in text
    assert "#SBATCH --cpus-per-task=8" in text
    assert "#SBATCH --mem=16G" in text
    assert "#SBATCH --gres" not in text
    assert "#SBATCH --gpus" not in text
    # This bounds only simultaneous lease *bring-up*. The slot is released as
    # soon as each tunnel is ready, so the evaluator can still reach 64 active
    # rollouts without stampeding vacli with 64 setup requests at once.
    assert 'VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-32}' in text
