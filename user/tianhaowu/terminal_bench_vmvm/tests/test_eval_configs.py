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


@pytest.mark.parametrize(
    "filename",
    [
        "mobius_kimi_k3_max_2500.toml",
        "mobius_qwen_a95b_2500.toml",
        "tb4_kimi_k3_approved_smoke.toml",
        "tb4_kimi_k3_max_miniswe.toml",
        "tb4_kimi_k3_shared24_miniswe.toml",
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
    }


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
            "tb4_kimi_k3_shared24_miniswe.toml",
            66,
            "9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892",
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
    maximum_concurrency = {
        "mobius_qwen_a95b_2500.toml": 64,
        "tb4_kimi_k3_shared24_miniswe.toml": 24,
    }.get(filename, 8)
    assert config["max_concurrent"] == config["multiplex"] <= maximum_concurrency
    expected_http_concurrency = 32 if filename == "mobius_qwen_a95b_2500.toml" else config["max_concurrent"]
    assert config["client"]["max_connections"] == expected_http_concurrency
    assert config["client"]["max_keepalive_connections"] == expected_http_concurrency
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


def test_kimi_shared24_tb4_contract() -> None:
    config = tomllib.loads((CONFIG_DIR / "tb4_kimi_k3_shared24_miniswe.toml").read_text())

    assert config["model"] == "Kimi-K3"
    assert config["num_tasks"] == 66
    assert config["num_rollouts"] == 1
    assert config["max_concurrent"] == 24
    assert config["multiplex"] == 24
    assert config["max_total_tokens"] == 262_144
    assert config["retain_traces"] is False
    assert config["client"]["capture_model_io"] is True
    assert config["client"]["max_connections"] == 24
    assert config["client"]["max_keepalive_connections"] == 24
    assert config["sampling"]["reasoning_effort"] == "max"
    assert "model.model_kwargs.timeout=15000" in config["harness"]["config_overrides"]
    assert config["harness"]["runtime"]["session_timeout"] == 43_200
    assert config["timeout"]["rollout"] == 36_000


def test_kimi_shared24_launch_recipe_is_fail_closed() -> None:
    readme = (CONFIG_DIR.parents[1] / "README.md").read_text()
    section = readme.split("### Shared 24-route Kimi deployment", 1)[1].split("###", 1)[0]

    assert "tb4_kimi_k3_shared24_miniswe.toml" in section
    assert "shared-kimi-k3/proxy_info.json" in section
    assert "VACLI_MAX_CONCURRENT_LEASES=2" in section
    assert "INFERENCE_DEPLOYMENT_ID=" not in section


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
    assert "resume_prime_rl=" in text
    assert "resume_verifiers=" in text
    assert "resume_renderers=" in text
    # This bounds simultaneous lease and reverse-forward setup. The slot is
    # released as soon as each setup probe passes, so it does not cap the
    # evaluator's number of active rollouts or live tunnels.
    assert "VACLI_MAX_CONCURRENT_LEASES=${VACLI_MAX_CONCURRENT_LEASES:-32}" in text


def test_direct_qwen_launcher_is_fail_closed() -> None:
    workflow_dir = CONFIG_DIR.parents[1]
    wrapper = (workflow_dir / "run_qwen_direct_eval.sbatch").read_text()

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


def test_qwen_affinity_smoke_uses_real_router_and_eval_client_cap32() -> None:
    workflow_dir = CONFIG_DIR.parents[1]
    smoke = (workflow_dir / "smoke_qwen_router_affinity.py").read_text()
    wrapper = (workflow_dir / "smoke_qwen_router_affinity.sbatch").read_text()

    assert "from verifiers.v1.clients import EvalClientConfig, resolve_client" in smoke
    assert "client.http.post(" in smoke
    assert "provider connection pool exceeded its configured bound" in smoke
    assert '"--max-concurrent-requests"' in smoke
    assert '"--queue-size"' in smoke
    assert "--provider-concurrency 32" in wrapper
    assert "--total-requests 64" in wrapper
    assert "mobius_qwen_a95b_2500.toml" in wrapper
    assert '"$router_site/STAGED"' in wrapper
    assert '"vllm-router=0.1.26"' in wrapper
    assert '"platform=x86_64-manylinux_2_28"' in wrapper
    assert '"$router_site/requirements.sha256"' in wrapper
    assert 'sha256sum "$router_site/requirements.txt"' in wrapper

    migration_wrapper = (workflow_dir / "migrate_qwen_router_admission.sbatch").read_text()
    assert "#SBATCH --partition=cpu_x86" in migration_wrapper
    assert '"$(uname -m)" != x86_64' in migration_wrapper
    assert "source_dir=${SOURCE_DIR:-}" in migration_wrapper
    assert "output_dir=${OUTPUT_DIR:-}" in migration_wrapper
    assert "deps/verifiers" in migration_wrapper
    assert "deps/renderers" in migration_wrapper
    assert "deps/pydantic-config/src" in migration_wrapper
    assert "migrate-admission" in migration_wrapper
