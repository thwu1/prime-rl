import hashlib
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
MOBIUS_TASK_FILE = CONFIG_DIR / "mobius_valid_tasks_2500.txt"


def _mobius_task_file_sha256() -> str:
    with MOBIUS_TASK_FILE.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


@pytest.mark.parametrize("config_path", EVAL_CONFIGS, ids=lambda path: path.name)
def test_eval_config_does_not_request_token_metadata(config_path: Path) -> None:
    config = tomllib.loads(config_path.read_text())

    assert FORBIDDEN_SAMPLING_FIELDS.isdisjoint(config.get("sampling", {}))


@pytest.mark.parametrize("config_path", EVAL_CONFIGS, ids=lambda path: path.name)
def test_eval_config_captures_model_io(config_path: Path) -> None:
    client = tomllib.loads(config_path.read_text())["client"]

    assert client["capture_model_io"] is True
    assert client["outbound_body_denylist"] == OUTBOUND_BODY_DENYLIST


@pytest.mark.parametrize("config_path", EVAL_CONFIGS, ids=lambda path: path.name)
def test_eval_config_retries_interception_failures(config_path: Path) -> None:
    config = tomllib.loads(config_path.read_text())
    retries = config.get("retries")
    if retries is None:
        return

    assert "InterceptionError" in retries["rollout"]["include"]


@pytest.mark.parametrize(
    "filename",
    [
        "mobius_kimi_k3_max_2500.toml",
        "mobius_kimi_k3_capacity_smoke.toml",
        "mobius_qwen_a95b_2500.toml",
        "tb4_kimi_k3_approved_smoke.toml",
        "tb4_kimi_k3_max_miniswe.toml",
        "tb4_kimi_token_smoke.toml",
        "tb4_qwen_a95b_miniswe.toml",
        "tb4_qwen_token_smoke.toml",
    ],
)
def test_miniswe_configs_pin_harness_model_retry_policy(filename: str) -> None:
    config = tomllib.loads((CONFIG_DIR / filename).read_text())

    # EvalClient is a transparent relay, so its BaseClientConfig.max_retries
    # field is not consumed. mini-swe-agent owns provider retries instead.
    assert "max_retries" not in config["client"]
    assert config["harness"]["env"]["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] == "10"
    if filename != "tb4_kimi_token_smoke.toml":
        assert "ProviderError" in config["retries"]["rollout"]["include"]
    assert "InterceptionError" in config["retries"]["rollout"]["include"]


def test_mobius_kimi_production_contract() -> None:
    config = tomllib.loads((CONFIG_DIR / "mobius_kimi_k3_max_2500.toml").read_text())

    assert config["model"] == "Kimi-K3"
    assert config["num_tasks"] == 2_500
    assert config["num_rollouts"] == 1
    assert config["max_concurrent"] == 8
    assert config["multiplex"] == 8
    assert config["max_input_tokens"] == 262_144
    assert config["max_output_tokens"] == 262_144
    assert config["max_total_tokens"] == 262_144
    assert config["retain_traces"] is False

    client = config["client"]
    assert client["capture_model_io"] is True
    assert client["max_connections"] == config["max_concurrent"]
    assert client["max_keepalive_connections"] == config["max_concurrent"]
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
    assert taskset["task_file"] == ("user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt")
    assert taskset["task_file_sha256"] == _mobius_task_file_sha256()
    tasks = MOBIUS_TASK_FILE.read_text().splitlines()
    assert len(tasks) == len(set(tasks)) == 2_500
    assert taskset["image_manifest"].endswith("/mobius_images.json")
    assert taskset["image_manifest_sha256"] == ("118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009")
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
        "InterceptionError",
    }


def test_mobius_kimi_capacity_smoke_matches_production_lane() -> None:
    config = tomllib.loads((CONFIG_DIR / "mobius_kimi_k3_capacity_smoke.toml").read_text())

    assert config["model"] == "Kimi-K3"
    assert config["num_tasks"] == 42
    assert config["num_rollouts"] == 1
    assert config["max_turns"] == 8
    assert config["max_concurrent"] == config["multiplex"] == 8
    assert config["max_input_tokens"] == 262_144
    assert config["max_output_tokens"] == 262_144
    assert config["max_total_tokens"] == 262_144
    assert config["retain_traces"] is False
    assert config["client"]["capture_model_io"] is True
    assert config["client"]["max_connections"] == 8
    assert config["client"]["max_keepalive_connections"] == 8
    assert config["client"]["outbound_body_denylist"] == OUTBOUND_BODY_DENYLIST
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["sampling"]["chat_template_kwargs"] == {
        "enable_thinking": True,
        "preserve_thinking": True,
    }
    taskset = config["taskset"]
    assert taskset["dataset_revision"] == "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
    assert taskset["task_file_sha256"] == "8d7d9377a9bbe6ade2fba7cc0730647d8be82402e225f95ad864a2218647563c"
    assert taskset["image_manifest_sha256"] == (
        "118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009"
    )


def test_mobius_qwen_production_retention_and_concurrency() -> None:
    config = tomllib.loads((CONFIG_DIR / "mobius_qwen_a95b_2500.toml").read_text())

    assert config["num_tasks"] == 2_500
    assert config["num_rollouts"] == 1
    assert config["max_concurrent"] == 8
    assert config["multiplex"] == 8
    assert config["max_total_tokens"] == 262_144
    assert config["sampling"]["max_tokens"] == 32_768
    assert config["retain_traces"] is False
    assert config["client"]["max_connections"] == 8
    assert config["client"]["max_keepalive_connections"] == 8
    taskset = config["taskset"]
    assert taskset["dataset_revision"] == "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
    assert taskset["task_file"] == ("user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt")
    assert taskset["task_file_sha256"] == _mobius_task_file_sha256()
    assert taskset["image_manifest_sha256"] == ("118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009")
    assert set(config["retries"]["rollout"]["include"]) == {
        "ProviderError",
        "SandboxError",
        "TunnelError",
        "InterceptionError",
    }


@pytest.mark.parametrize(
    ("filename", "expected_count", "expected_sha256"),
    [
        (
            "tb4_qwen_token_smoke.toml",
            2,
            "4ae515a77f33746ecb598ab6c670612265bd1ef726eb6ca7f16cc81f5e191c25",
        ),
        (
            "tb4_kimi_k3_approved_smoke.toml",
            2,
            "ecdcbc6e4f54b690e64b4566de5eecf33467088c8ca3436738cd7308d4e45b83",
        ),
        (
            "tb4_qwen_a95b_miniswe.toml",
            66,
            "9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892",
        ),
        (
            "tb4_kimi_k3_max_miniswe.toml",
            66,
            "9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892",
        ),
        (
            "mobius_kimi_k3_capacity_smoke.toml",
            42,
            "8d7d9377a9bbe6ade2fba7cc0730647d8be82402e225f95ad864a2218647563c",
        ),
        (
            "mobius_qwen_a95b_2500.toml",
            2_500,
            _mobius_task_file_sha256(),
        ),
    ],
)
def test_eval_configs_pin_approved_tasks_and_runtime_contract(
    filename: str, expected_count: int, expected_sha256: str
) -> None:
    config = tomllib.loads((CONFIG_DIR / filename).read_text())

    assert config["max_input_tokens"] == 262_144
    assert config["max_output_tokens"] == 262_144
    assert config["max_total_tokens"] == 262_144
    assert config["sampling"]["max_tokens"] == 32_768
    assert config["sampling"]["chat_template_kwargs"] == {
        "enable_thinking": True,
        "preserve_thinking": True,
    }
    assert config["max_concurrent"] == config["multiplex"] <= 8
    assert config["client"]["max_connections"] == config["max_concurrent"]
    assert config["client"]["max_keepalive_connections"] == config["max_concurrent"]
    assert config["client"]["timeout"] == 7_200
    assert config["harness"]["runtime"]["type"] == "vmvm"
    assert config["timeout"]["setup"] >= 3_600
    assert config["timeout"]["rollout"] >= 28_800
    assert config["timeout"]["finalize"] >= 3_600
    assert config["timeout"]["scoring"] >= 21_600

    taskset = config["taskset"]
    assert "tasks" not in taskset
    assert taskset["task_file_sha256"] == expected_sha256
    task_file = CONFIG_DIR.parents[4] / taskset["task_file"]
    task_bytes = task_file.read_bytes()
    tasks = task_bytes.decode().splitlines()
    assert hashlib.sha256(task_bytes).hexdigest() == expected_sha256
    assert len(tasks) == len(set(tasks)) == expected_count
    if filename == "tb4_qwen_token_smoke.toml":
        assert tasks == ["ctr-optimization", "vllm-deepseek-streaming"]
    elif expected_count == 66:
        shard_tasks = {
            task
            for shard in (
                "tb4_kimi_k3_direct_a.tasks.txt",
                "tb4_kimi_k3_direct_b.tasks.txt",
            )
            for task in (CONFIG_DIR / shard).read_text().splitlines()
        }
        assert set(tasks) == shard_tasks


def test_kimi_tb4_config_pins_single_route_qualification_concurrency() -> None:
    config = tomllib.loads((CONFIG_DIR / "tb4_kimi_k3_max_miniswe.toml").read_text())

    assert config["max_concurrent"] == 4
    assert config["multiplex"] == 4
    assert config["client"]["max_connections"] == 4
    assert config["client"]["max_keepalive_connections"] == 4


@pytest.mark.parametrize(
    "filename",
    ["tb4_kimi_k3_direct_a.toml", "tb4_kimi_k3_direct_b.toml"],
)
def test_direct_kimi_configs_pin_measured_safe_concurrency(filename: str) -> None:
    config = tomllib.loads((CONFIG_DIR / filename).read_text())

    assert config["num_tasks"] == 33
    assert config["max_concurrent"] == 4
    assert config["multiplex"] == 4
    assert config["client"]["max_connections"] == 4
    assert config["client"]["max_keepalive_connections"] == 4


def test_kimi_smoke_config_pins_approved_tasks() -> None:
    config = tomllib.loads((CONFIG_DIR / "tb4_kimi_token_smoke.toml").read_text())

    assert config["num_tasks"] == 2
    assert config["max_concurrent"] == 2
    assert config["multiplex"] == 2
    taskset = config["taskset"]
    assert "tasks" not in taskset
    assert taskset["task_file"] == ("user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_token_smoke.tasks.txt")
    assert taskset["task_file_sha256"] == ("ecdcbc6e4f54b690e64b4566de5eecf33467088c8ca3436738cd7308d4e45b83")
    task_file = CONFIG_DIR.parents[4] / taskset["task_file"]
    task_bytes = task_file.read_bytes()
    assert hashlib.sha256(task_bytes).hexdigest() == taskset["task_file_sha256"]
    assert len(task_bytes.decode().splitlines()) == 2


def test_eval_controller_is_cpu_only_and_supports_high_vmvm_concurrency() -> None:
    wrapper = CONFIG_DIR.parents[1] / "run_eval.sbatch"
    text = wrapper.read_text()

    assert "#SBATCH --partition=cpu_x86" in text
    assert "#SBATCH --qos=cpu_x86_lowest" in text
    assert "#SBATCH --cpus-per-task=8" in text
    assert "#SBATCH --mem=16G" in text
    assert "#SBATCH --gres" not in text
    assert "#SBATCH --gpus" not in text
    assert 'python3 "$workflow_dir/eval_run_identity.py"' in text
    assert "--mode \"$identity_mode\"" in text
    assert "eval_run_identity_sha256" in text
    # This bounds only simultaneous lease *bring-up*. The slot is released as
    # soon as each tunnel is ready, so the evaluator can still reach 64 active
    # rollouts without stampeding vacli with 64 setup requests at once.
    assert "VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-32}" in text


def test_kimi_tb4_gate_sequences_smoke_before_full_evaluation() -> None:
    wrapper = (CONFIG_DIR.parents[1] / "run_kimi_tb4_gate.sbatch").read_text()

    assert "ed1d83d5905bdd2db87ffbbe16e9374b9bd28ddd" in wrapper
    assert "EVAL_RUN_ROLE=smoke" in wrapper
    assert "EVAL_RUN_ROLE=tb4" in wrapper
    assert "SMOKE_EXPECTED_TRACES=2" in wrapper
    assert "KIMI_TB4_STOP_AFTER_SMOKE" in wrapper
    assert 'if [[ "$stop_after_smoke" == 1 ]]' in wrapper
    assert "VACLI_MAX_CONCURRENT_LEASES=2" in wrapper
    assert "validate_endpoint_binding" in wrapper
    assert 'export INFERENCE_PROXY_INFO_SHA256="$proxy_info_sha256"' in wrapper
    assert wrapper.count("run_with_proxy_guard") == 5
    assert "run_trace_smoke_audit.sbatch" in wrapper
    assert "run_tb4_audit.sbatch" in wrapper
    assert wrapper.index("EVAL_RUN_ROLE=smoke") < wrapper.index("run_trace_smoke_audit.sbatch")
    assert wrapper.index("run_trace_smoke_audit.sbatch") < wrapper.index("EVAL_RUN_ROLE=tb4")
    assert wrapper.index("EVAL_RUN_ROLE=tb4") < wrapper.index("run_tb4_audit.sbatch")


def test_direct_qwen_launcher_is_fail_closed() -> None:
    workflow_dir = CONFIG_DIR.parents[1]
    wrapper = (workflow_dir / "run_qwen_direct_eval.sbatch").read_text()
    driver = (workflow_dir / "run_direct_qwen_eval_driver.sh").read_text()

    assert "--policy consistent_hash" in wrapper
    assert "--request-id-headers x-session-id" in wrapper
    assert "--request-timeout-secs 7500" in wrapper
    assert "--disable-retries" in wrapper
    assert "--max-concurrent-requests 8" in wrapper
    assert "--queue-size 0" in wrapper
    assert "VACLI_MAX_CONCURRENT_LEASES=8" in wrapper
    assert "OPENAI_API_KEY=EMPTY" in wrapper
    assert "INFERENCE_PROXY_INFO" in wrapper
    assert "direct_workers.json" in wrapper
    assert "approved task_file and task_file_sha256" in wrapper
    assert "DIRECT_QWEN_APPROVED_TASK_FILE" in wrapper
    assert "DIRECT_QWEN_APPROVED_TASK_FILE_SHA256" in wrapper
    assert "validate_saved_manifest" in driver
    assert "validate_eval_config" in driver
    assert "load_workers" in driver
    assert "snapshot_eval_inputs.py" in driver
    assert "validate_task_approval.py" in driver
    assert '.writer.lock"' in driver
    assert "Direct Qwen driver received a forbidden generic-eval override" in driver


def test_direct_qwen_router_probe_is_infrastructure_only() -> None:
    workflow_dir = CONFIG_DIR.parents[1]
    wrapper = (workflow_dir / "probe_qwen_direct_router.sbatch").read_text()

    assert "/v1/models" in wrapper
    assert "vllm_router_active_workers" in wrapper
    assert "/chat/completions" not in wrapper
    assert "run_eval.sbatch" not in wrapper
    assert "EVAL_CONFIG" not in wrapper
