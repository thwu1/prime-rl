import hashlib
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from eval_run_identity import EvalIdentityError, _contract, _resolved_config_data
from verifiers.v1.configs.eval import EvalConfig
from verifiers.v1.retries import RolloutRetryConfig, should_retry

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
ACTIVE_KIMI_CONFIGS = [
    "mobius_kimi_k3_capacity_smoke.toml",
    "mobius_kimi_k3_max_2500.toml",
    "tb4_kimi_k3_approved_smoke.toml",
    "tb4_kimi_k3_max_miniswe.toml",
]
ACTIVE_QWEN_CONFIGS = [
    "mobius_qwen_a95b_2500.toml",
    "shared_qwen38_2p4t/mobius_qwen_a95b_2500_sandoq.toml",
    "tb4_qwen_a95b_miniswe.toml",
    "tb4_qwen_token_smoke.toml",
]
BASE_ROLLOUT_RETRY_ERRORS = {
    "ProviderError",
    "SandboxError",
    "TunnelError",
}
KIMI_ROLLOUT_RETRY_ERRORS = BASE_ROLLOUT_RETRY_ERRORS | {"InterceptionError"}
QWEN_ROLLOUT_RETRY_ERRORS = BASE_ROLLOUT_RETRY_ERRORS | {"InterceptionError"}
KIMI_TOKEN_SMOKE_RETRY_ERRORS = KIMI_ROLLOUT_RETRY_ERRORS - {"ProviderError"}
PRODUCTION_KIMI_CONFIG_ROLES = [
    ("mobius_kimi_k3_capacity_smoke.toml", "smoke"),
    ("mobius_kimi_k3_max_2500.toml", "mobius"),
    ("tb4_kimi_k3_approved_smoke.toml", "smoke"),
    ("tb4_kimi_k3_direct_a.toml", "tb4"),
    ("tb4_kimi_k3_direct_b.toml", "tb4"),
    ("tb4_kimi_k3_max_miniswe.toml", "tb4"),
]


def _mobius_task_file_sha256() -> str:
    with MOBIUS_TASK_FILE.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _resolved_eval_config(filename: str) -> dict:
    raw = tomllib.loads((CONFIG_DIR / filename).read_text())
    return _resolved_config_data(EvalConfig.model_validate(raw), explicit=raw)


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
    ("filename", "rollout_timeout", "session_timeout", "retry_exceptions"),
    [
        ("mobius_kimi_k3_capacity_smoke.toml", 36_000, 43_200, KIMI_ROLLOUT_RETRY_ERRORS),
        ("mobius_kimi_k3_max_2500.toml", 36_000, 43_200, KIMI_ROLLOUT_RETRY_ERRORS),
        ("tb4_kimi_k3_approved_smoke.toml", 28_800, 32_400, KIMI_ROLLOUT_RETRY_ERRORS),
        ("tb4_kimi_k3_direct_a.toml", 36_000, 43_200, KIMI_ROLLOUT_RETRY_ERRORS),
        ("tb4_kimi_k3_direct_b.toml", 36_000, 43_200, KIMI_ROLLOUT_RETRY_ERRORS),
        ("tb4_kimi_k3_max_miniswe.toml", 36_000, 43_200, KIMI_ROLLOUT_RETRY_ERRORS),
        ("tb4_kimi_token_smoke.toml", 28_800, 32_400, KIMI_TOKEN_SMOKE_RETRY_ERRORS),
    ],
)
def test_kimi_configs_pin_exact_timeout_and_retry_contract(
    filename: str,
    rollout_timeout: int,
    session_timeout: int,
    retry_exceptions: set[str],
) -> None:
    config = tomllib.loads((CONFIG_DIR / filename).read_text())

    assert config["client"]["timeout"] == 43_200
    assert config["client"]["connect_timeout"] == 120
    assert config["harness"]["config_overrides"].count("model.model_kwargs.timeout=43200") == 1
    assert config["harness"]["runtime"]["session_timeout"] == session_timeout
    assert config["timeout"] == {
        "setup": 3_600,
        "rollout": rollout_timeout,
        "finalize": 3_600,
        "scoring": 21_600,
    }
    rollout_retries = config["retries"]["rollout"]
    expected_retries = 0 if "sandoq" in filename else 2
    assert rollout_retries["max_retries"] == expected_retries
    assert len(rollout_retries["include"]) == len(retry_exceptions)
    assert set(rollout_retries["include"]) == retry_exceptions
    assert "HarnessError" not in rollout_retries["include"]


@pytest.mark.parametrize(("filename", "role"), PRODUCTION_KIMI_CONFIG_ROLES)
def test_each_production_kimi_config_passes_its_real_role_contract(filename: str, role: str) -> None:
    config = _resolved_eval_config(filename)

    _contract(config, "Kimi-K3", role=role)


@pytest.mark.parametrize(
    ("filename", "role"),
    [
        ("mobius_kimi_k3_capacity_smoke.toml", "smoke"),
        ("mobius_kimi_k3_max_2500.toml", "mobius"),
    ],
)
def test_mobius_kimi_roles_reject_misaligned_steady_state_concurrency(filename: str, role: str) -> None:
    config = _resolved_eval_config(filename)
    config["client"]["max_keepalive_connections"] -= 1

    with pytest.raises(EvalIdentityError, match="^kimi_steady_state_concurrency_mismatch$"):
        _contract(config, "Kimi-K3", role=role)


def test_legacy_token_smoke_is_not_production_run_identity_qualified() -> None:
    config = _resolved_eval_config("tb4_kimi_token_smoke.toml")

    with pytest.raises(EvalIdentityError, match="^kimi_retry_contract_invalid$"):
        _contract(config, "Kimi-K3", role="smoke")


def test_checked_in_kimi_configs_reject_cross_profile_and_retry_policy() -> None:
    smoke = _resolved_eval_config("tb4_kimi_k3_approved_smoke.toml")
    with pytest.raises(EvalIdentityError, match="^kimi_timeout_contract_invalid$"):
        _contract(smoke, "Kimi-K3", role="tb4")

    full = _resolved_eval_config("tb4_kimi_k3_max_miniswe.toml")
    with pytest.raises(EvalIdentityError, match="^kimi_timeout_contract_invalid$"):
        _contract(full, "Kimi-K3", role="smoke")

    missing = _resolved_eval_config("tb4_kimi_k3_max_miniswe.toml")
    missing["retries"]["rollout"]["include"].remove("InterceptionError")
    with pytest.raises(EvalIdentityError, match="^kimi_retry_contract_invalid$"):
        _contract(missing, "Kimi-K3", role="tb4")

    broad = _resolved_eval_config("tb4_kimi_k3_max_miniswe.toml")
    broad["retries"]["rollout"]["include"][-1] = "HarnessError"
    with pytest.raises(EvalIdentityError, match="^kimi_retry_contract_invalid$"):
        _contract(broad, "Kimi-K3", role="tb4")


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
    if "kimi" in filename:
        assert config["harness"]["config_overrides"].count("model.model_kwargs.timeout=43200") == 1
    if filename != "tb4_kimi_token_smoke.toml":
        assert "ProviderError" in config["retries"]["rollout"]["include"]


@pytest.mark.parametrize("filename", ACTIVE_KIMI_CONFIGS + ACTIVE_QWEN_CONFIGS)
def test_active_rollout_retry_policy_is_model_specific(filename: str) -> None:
    config = tomllib.loads((CONFIG_DIR / filename).read_text())
    rollout_retries = config["retries"]["rollout"]

    expected_retries = 0 if "sandoq" in filename else 2
    assert rollout_retries["max_retries"] == expected_retries
    expected_by_model = {
        "Kimi-K3": KIMI_ROLLOUT_RETRY_ERRORS,
        "Qwen3.8-2.4T-A95B": QWEN_ROLLOUT_RETRY_ERRORS,
    }
    expected = expected_by_model[config["model"]]
    assert set(rollout_retries["include"]) == expected
    assert "HarnessError" not in rollout_retries["include"]

    retry = RolloutRetryConfig.model_validate(rollout_retries)
    interception_trace = SimpleNamespace(error=SimpleNamespace(type="InterceptionError"))
    harness_trace = SimpleNamespace(error=SimpleNamespace(type="HarnessError"))
    assert should_retry(interception_trace, retry) is True
    assert should_retry(harness_trace, retry) is False


def test_mobius_kimi_production_contract() -> None:
    config = tomllib.loads((CONFIG_DIR / "mobius_kimi_k3_max_2500.toml").read_text())

    assert config["model"] == "Kimi-K3"
    assert config["num_tasks"] == 2_500
    assert config["num_rollouts"] == 1
    assert config["max_concurrent"] == 24
    assert config["multiplex"] == 24
    assert config["max_input_tokens"] == 262_144
    assert config["max_output_tokens"] == 262_144
    assert config["max_total_tokens"] == 262_144
    assert config["retain_traces"] is False

    client = config["client"]
    assert client["capture_model_io"] is True
    assert client["max_connections"] == config["max_concurrent"]
    assert client["max_keepalive_connections"] == config["max_concurrent"]
    assert client["timeout"] == 43_200
    assert client["connect_timeout"] == 120
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
    assert runtime["session_timeout"] == 43_200
    assert runtime["lease_ttl"] == "60s"

    timeouts = config["timeout"]
    assert timeouts["setup"] == 3_600
    assert timeouts["rollout"] == 36_000
    assert timeouts["rollout"] < runtime["session_timeout"] <= client["timeout"]
    assert timeouts["finalize"] == 3_600
    assert timeouts["scoring"] == 21_600

    rollout_retries = config["retries"]["rollout"]
    assert rollout_retries["max_retries"] == 2
    assert set(rollout_retries["include"]) == {
        "ProviderError",
        "SandboxError",
        "InterceptionError",
        "TunnelError",
    }


def test_mobius_kimi_capacity_smoke_matches_production_lane() -> None:
    config = tomllib.loads((CONFIG_DIR / "mobius_kimi_k3_capacity_smoke.toml").read_text())

    assert config["model"] == "Kimi-K3"
    assert config["num_tasks"] == 42
    assert config["num_rollouts"] == 1
    assert config["max_turns"] == 8
    assert config["max_concurrent"] == config["multiplex"] == 24
    assert config["max_input_tokens"] == 262_144
    assert config["max_output_tokens"] == 262_144
    assert config["max_total_tokens"] == 262_144
    assert config["retain_traces"] is False
    assert config["client"]["capture_model_io"] is True
    assert config["client"]["max_connections"] == 24
    assert config["client"]["max_keepalive_connections"] == 24
    assert config["client"]["timeout"] == 43_200
    assert config["harness"]["runtime"]["session_timeout"] == 43_200
    assert config["timeout"]["rollout"] == 36_000
    assert config["timeout"]["rollout"] < config["harness"]["runtime"]["session_timeout"] <= config["client"]["timeout"]
    assert config["client"]["outbound_body_denylist"] == OUTBOUND_BODY_DENYLIST
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["sampling"]["chat_template_kwargs"] == {
        "enable_thinking": True,
        "preserve_thinking": True,
    }
    taskset = config["taskset"]
    assert taskset["dataset_revision"] == "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
    assert taskset["task_file_sha256"] == "8d7d9377a9bbe6ade2fba7cc0730647d8be82402e225f95ad864a2218647563c"
    assert taskset["image_manifest_sha256"] == ("118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009")


def test_mobius_qwen_production_retention_and_concurrency() -> None:
    config = tomllib.loads((CONFIG_DIR / "mobius_qwen_a95b_2500.toml").read_text())

    assert config["num_tasks"] == 2_500
    assert config["num_rollouts"] == 1
    assert config["max_concurrent"] == 64
    assert config["multiplex"] == 64
    assert config["max_total_tokens"] == 262_144
    assert config["sampling"]["max_tokens"] == 32_768
    assert config["retain_traces"] is False
    assert config["client"]["max_connections"] == 32
    assert config["client"]["max_keepalive_connections"] == 32
    assert "model.model_kwargs.timeout=15000" in config["harness"]["config_overrides"]
    taskset = config["taskset"]
    assert taskset["dataset_revision"] == "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
    assert taskset["task_file"] == ("user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt")
    assert taskset["task_file_sha256"] == _mobius_task_file_sha256()
    assert taskset["image_manifest_sha256"] == ("118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009")
    assert set(config["retries"]["rollout"]["include"]) == QWEN_ROLLOUT_RETRY_ERRORS


def test_mobius_qwen_sandoq_contract_is_explicit_and_digest_pinned() -> None:
    config = tomllib.loads(
        (
            CONFIG_DIR
            / "shared_qwen38_2p4t/mobius_qwen_a95b_2500_sandoq.toml"
        ).read_text()
    )

    assert config["num_tasks"] == 2_500
    assert config["max_concurrent"] == config["multiplex"] == 64
    assert config["taskset"]["image_manifest"].endswith("/mobius_images.sandoq.json")
    assert config["taskset"]["image_manifest_sha256"] == (
        "a3fb4ec9ac9d1ee8376013013f171584c288321923f2050177157edac58340c8"
    )
    runtime = config["harness"]["runtime"]
    assert runtime == {
        "type": "sandoq",
        "mode": "oci-runner",
        "session_timeout": 43_200,
        "network_access": True,
        "host_tunnel": "none",
        "expected_environment": "oci-runner",
        "ecr_token_file": "/storage/home/tianhaowu/.config/oci-runner/ecr-token",
    }
    assert set(config["retries"]["rollout"]["include"]) == QWEN_ROLLOUT_RETRY_ERRORS

    resolved = _resolved_eval_config(
        "shared_qwen38_2p4t/mobius_qwen_a95b_2500_sandoq.toml"
    )
    _contract(
        resolved,
        "Qwen3.8-2.4T-A95B",
        role="mobius",
        sandbox_provider="sandoq",
    )
    with pytest.raises(EvalIdentityError, match="vmvm_runtime_required"):
        _contract(resolved, "Qwen3.8-2.4T-A95B", role="mobius")


@pytest.mark.parametrize(
    ("filename", "expected_count", "expected_sha256", "expected_concurrency"),
    [
        (
            "tb4_qwen_token_smoke.toml",
            2,
            "4ae515a77f33746ecb598ab6c670612265bd1ef726eb6ca7f16cc81f5e191c25",
            2,
        ),
        (
            "tb4_kimi_k3_approved_smoke.toml",
            2,
            "ecdcbc6e4f54b690e64b4566de5eecf33467088c8ca3436738cd7308d4e45b83",
            2,
        ),
        (
            "tb4_qwen_a95b_miniswe.toml",
            66,
            "9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892",
            8,
        ),
        (
            "tb4_kimi_k3_max_miniswe.toml",
            66,
            "9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892",
            4,
        ),
        (
            "mobius_kimi_k3_capacity_smoke.toml",
            42,
            "8d7d9377a9bbe6ade2fba7cc0730647d8be82402e225f95ad864a2218647563c",
            24,
        ),
        (
            "mobius_qwen_a95b_2500.toml",
            2_500,
            _mobius_task_file_sha256(),
            64,
        ),
    ],
)
def test_eval_configs_pin_approved_tasks_and_runtime_contract(
    filename: str,
    expected_count: int,
    expected_sha256: str,
    expected_concurrency: int,
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
    assert config["max_concurrent"] == config["multiplex"] == expected_concurrency
    expected_http_concurrency = 32 if filename == "mobius_qwen_a95b_2500.toml" else expected_concurrency
    assert config["client"]["max_connections"] == expected_http_concurrency
    assert config["client"]["max_keepalive_connections"] == expected_http_concurrency
    expected_client_timeout = 43_200 if "kimi" in filename else 7_200
    assert config["client"]["timeout"] == expected_client_timeout
    assert config["harness"]["runtime"]["type"] == "vmvm"
    assert config["timeout"]["setup"] >= 3_600
    expected_rollout_timeout = 28_800
    assert config["timeout"]["rollout"] >= expected_rollout_timeout
    if "kimi" in filename:
        assert (
            config["timeout"]["rollout"]
            < config["harness"]["runtime"]["session_timeout"]
            <= config["client"]["timeout"]
        )
        assert config["timeout"]["rollout"] < 43_200 <= config["client"]["timeout"]
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


def test_documented_kimi_direct_launches_pin_the_exact_project_revision() -> None:
    workflow_dir = CONFIG_DIR.parents[1]
    for document in (workflow_dir / "README.md", workflow_dir / "HANDOFF.md"):
        launch_lines = [
            line for line in document.read_text().splitlines() if "run_eval.sbatch" in line and "kimi" in line.lower()
        ]
        assert launch_lines
        assert all("EVAL_EXPECTED_PRIME_RL_REVISION=<commit>" in line for line in launch_lines)


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
    assert '--mode "$identity_mode"' in text
    assert "eval_run_identity_sha256" in text
    # This bounds only simultaneous lease *bring-up*. The slot is released as
    # soon as each tunnel is ready, so the evaluator can still reach 64 active
    # rollouts without stampeding vacli with 64 setup requests at once.
    assert "VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-32}" in text
    assert "get_gateway_adapter" in text
    assert "create_client(config)" in text
    assert "verify_references=True" in text
    assert "sandoq_pool_cleanup.py" in text
    assert "sanitize_sandoq_cleanup_audit.py" in text
    assert text.index("worktrees must all be clean") < text.index("create_client(config)")
    assert text.index("approved cutover source") < text.index("create_client(config)")
    assert text.index("approved closure") < text.index("create_client(config)")


def test_kimi_tb4_gate_sequences_smoke_before_full_evaluation() -> None:
    wrapper = (CONFIG_DIR.parents[1] / "run_kimi_tb4_gate.sbatch").read_text()

    assert "EVAL_EXPECTED_PRIME_RL_REVISION:?" in wrapper
    assert '!= "$expected_project_revision"' in wrapper
    assert 'export EVAL_EXPECTED_PRIME_RL_REVISION="$expected_project_revision"' in wrapper
    assert "ed1d83d5905bdd2db87ffbbe16e9374b9bd28ddd" not in wrapper
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


def test_trace_smoke_audit_wrapper_exposes_exact_provider_json_opt_in() -> None:
    wrapper = (CONFIG_DIR.parents[1] / "run_trace_smoke_audit.sbatch").read_text()

    assert "SMOKE_REQUIRE_EXACT_PROVIDER_JSON:-0" in wrapper
    assert "SMOKE_REQUIRE_EXACT_PROVIDER_JSON must be 0 or 1" in wrapper
    assert "SMOKE_CHECKPOINT_NAME:-smoke_checkpoint.json" in wrapper
    assert "SMOKE_CHECKPOINT_NAME must be a safe smoke checkpoint basename" in wrapper
    assert "Alternate smoke checkpoints require exact provider JSON" in wrapper
    assert "args+=(--require-exact-provider-json)" in wrapper
    assert '--checkpoint-name "$checkpoint_name"' in wrapper


def test_direct_qwen_launcher_is_fail_closed() -> None:
    workflow_dir = CONFIG_DIR.parents[1]
    wrapper = (workflow_dir / "run_qwen_direct_eval.sbatch").read_text()
    driver = (workflow_dir / "run_direct_qwen_eval_driver.sh").read_text()

    assert "#SBATCH --time=7-00:00:00" in wrapper

    assert '--policy "$router_policy"' in wrapper
    assert '--request-id-headers "$router_request_id_header"' in wrapper
    assert '[[ "$router_policy" != consistent_hash ]]' in wrapper
    assert '[[ "$router_request_id_header" != x-session-id ]]' in wrapper
    assert "round_robin" not in wrapper
    assert "--request-timeout-secs 7500" in wrapper
    assert "--disable-retries" in wrapper
    assert '--max-concurrent-requests "$router_max_concurrent"' in wrapper
    assert '--queue-size "$router_queue_size"' in wrapper
    assert '--queue-timeout-secs "$router_queue_timeout"' in wrapper
    assert "router_max_concurrent != expected_router_max_concurrent" in wrapper
    assert "router_queue_size != expected_router_queue_size" in wrapper
    assert "router_max_concurrent > 32" in wrapper
    assert "router_queue_size >= 64" in wrapper
    assert "router_max_concurrent + router_queue_size > 64" in wrapper
    assert "expected_rollout_concurrency=96" in wrapper
    assert "expected_router_max_concurrent=48" in wrapper
    assert "expected_router_queue_size=48" in wrapper
    assert 'export DIRECT_QWEN_PROVIDER_CONCURRENCY="$router_max_concurrent"' in wrapper
    assert 'export VACLI_MAX_CONCURRENT_LEASES="$expected_vmvm_lease_concurrency"' in wrapper
    assert "expected_vmvm_lease_concurrency=4" in wrapper
    assert "capacity-smoke" in wrapper
    assert "repair_generation_config.toml" in wrapper
    assert "#SBATCH --mem=32G" in wrapper
    assert "OPENAI_API_KEY=EMPTY" in wrapper
    assert "INFERENCE_PROXY_INFO" in wrapper
    assert "direct_workers.json" in wrapper
    assert "approved task_file and task_file_sha256" in wrapper
    assert "DIRECT_QWEN_APPROVED_TASK_FILE" in wrapper
    assert "DIRECT_QWEN_APPROVED_TASK_FILE_SHA256" in wrapper
    assert 'export DIRECT_QWEN_MANIFEST_SHA256="$manifest_sha256"' in wrapper
    assert 'export DIRECT_QWEN_ROUTER_POLICY="$router_policy"' in wrapper
    assert 'export DIRECT_QWEN_REQUEST_ID_HEADERS="$router_request_id_header"' in wrapper
    assert "validate_saved_manifest" in driver
    assert "validate_eval_config" in driver
    assert "load_workers" in driver
    assert "snapshot_eval_inputs.py" in driver
    assert "validate_task_approval.py" in driver
    assert '.writer.lock"' in driver
    assert "Direct Qwen driver received a forbidden generic-eval override" in driver
    assert '[[ "$sandbox_provider" == sandoq && -n "$resume_dir" ]]' in driver
    provider_context = (
        workflow_dir / "terminal_bench_vmvm/sandoq_provider_context.py"
    ).read_text()
    assert 'ENVIRONMENT = "oci-runner"' in provider_context
    assert "SANDOQ_EFFECTIVE_TASK_NETWORK" in driver
    assert "sandoq_site_sha256" in driver
    assert "unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy" in driver
    assert '${#worker_urls[@]} -ne "$expected_worker_count"' in wrapper
    assert '"$active_workers" == "$expected_worker_count"' in wrapper
    assert "expected_worker_count=24" in wrapper
    assert "expected_worker_count=16" not in wrapper
    assert "Sandoq ramps require a fresh task-bound live24 manifest" in wrapper
    assert "--preflight" in wrapper
    assert "--role qwen-direct --sandbox-provider sandoq" in driver
    assert 'args=(--resume "$output_dir")' in driver
    assert "eval_run_identity.py" in driver
    assert "certify_direct_qwen_sandoq.py" in wrapper
    assert '"$OCI_RUNNER_POOL_MIN_SIZE" != 0' in driver
    assert 'expected_pool_socket="$pool_socket_dir/${SLURM_JOB_ID:?}.sock"' in driver
    assert '"$output_dir/pool_events.jsonl"' in driver
    assert '"$output_dir/control/sandoq-pool.wal.jsonl"' in driver
    assert "SANDOQ_RAMP_RECEIPT" in driver
    assert "validate_predecessor" in driver
    assert "verify_references=True" in driver
    assert "sandoq_pool_cleanup.py" in driver
    assert "sanitize_sandoq_cleanup_audit.py" in driver
    assert "router was not live at certification" in wrapper
    assert "no longer has exactly 24 active workers" in wrapper
    assert "serving generation drifted during evaluation" in wrapper
    assert "validate_post_eval_generation" in wrapper
    assert "f7313db42eea4b3be8bcbe16a8072f73cf6abed5" in wrapper
    assert "f7313db42eea4b3be8bcbe16a8072f73cf6abed5" in driver
    assert "80e58e7e2b194e9c1b8dc0990c00b7a839127eea" in driver
    assert "configs/eval/shared_qwen38_2p4t/mobius_qwen_a95b_2500_sandoq.toml" in wrapper
    assert wrapper.index("approved clean source closure") < wrapper.index('"$workflow_dir/direct_qwen_workers.py"')

    generic_wrapper = (workflow_dir / "run_eval.sbatch").read_text()
    assert "direct_qwen_manifest_sha256=" in generic_wrapper
    assert "direct_qwen_router_policy=" in generic_wrapper
    assert "direct_qwen_request_id_headers=" in generic_wrapper
    assert "resume_direct_qwen_manifest_sha256=" in generic_wrapper
    assert "direct_qwen_provider_concurrency=" in generic_wrapper
    assert "resume_direct_qwen_provider_concurrency=" in generic_wrapper
    assert "qwen_serving_generation_capacity_smoke_sha256=" in generic_wrapper


def test_direct_qwen_router_probe_is_infrastructure_only() -> None:
    workflow_dir = CONFIG_DIR.parents[1]
    wrapper = (workflow_dir / "probe_qwen_direct_router.sbatch").read_text()

    assert "/v1/models" in wrapper
    assert "vllm_router_active_workers" in wrapper
    assert "/chat/completions" not in wrapper
    assert "run_eval.sbatch" not in wrapper
    assert "EVAL_CONFIG" not in wrapper
