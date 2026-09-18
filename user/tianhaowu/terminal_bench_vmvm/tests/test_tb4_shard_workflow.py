from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
import stat
import tomllib
from dataclasses import replace
from pathlib import Path

import eval_run_identity
import guard_success_receipt
import mobius_launch_certificate
import pytest
import tb4_shard_workflow as workflow
from tb4_shard_workflow import (
    CertifiedShard,
    ShardWorkflowError,
    _config_semantics_sha256,
    _hold_writer_lock,
    _scan_results,
    _validate_base_config,
    create_plan,
    load_plan,
    merge_multigen_shards,
    merge_shards,
    validate_multigen_sharded_checkpoint,
    validate_sharded_checkpoint,
)


def _private_write(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _identifiers() -> list[str]:
    return [hashlib.sha256(f"synthetic-case-{index}".encode()).hexdigest() for index in range(66)]


def _universe(tmp_path: Path) -> tuple[Path, str, list[str]]:
    identifiers = _identifiers()
    path = tmp_path / "private-universe.txt"
    raw = "".join(f"{identifier}\n" for identifier in identifiers).encode()
    _private_write(path, raw)
    return path, hashlib.sha256(raw).hexdigest(), identifiers


def _base_config(tmp_path: Path, universe_path: Path, universe_sha256: str) -> Path:
    path = tmp_path / "base.toml"
    path.write_text(
        f'''model = "Kimi-K3"
num_tasks = 66
num_rollouts = 1
max_concurrent = 4
multiplex = 4
max_input_tokens = 262144
max_output_tokens = 262144
max_total_tokens = 262144
retain_traces = false
rich = false

[client]
type = "eval"
base_url = "http://localhost.invalid/v1"
api_key_var = "OPENAI_API_KEY"
capture_model_io = true
outbound_body_denylist = ["logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"]
max_connections = 4
max_keepalive_connections = 4
timeout = 43200
connect_timeout = 120
headers = {{}}

[sampling]
reasoning_effort = "max"
max_tokens = 262144

[sampling.chat_template_kwargs]
enable_thinking = true
preserve_thinking = true

[taskset]
id = "terminal-bench-vmvm"
task_file = "{universe_path}"
task_file_sha256 = "{universe_sha256}"
dataset_dir = "/private/dataset"

[harness]
config_overrides = ["model.model_kwargs.timeout=43200"]
[harness.runtime]
type = "vmvm"
session_timeout = 43200

[timeout]
setup = 3600
rollout = 36000
finalize = 3600
scoring = 21600

[retries.rollout]
max_retries = 2
include = ["ProviderError", "SandboxError", "TunnelError", "InterceptionError"]
'''
    )
    return path


def _make_plan(tmp_path: Path, *, shard_size: int = 4):
    universe, universe_sha, identifiers = _universe(tmp_path)
    base = _base_config(tmp_path, universe, universe_sha)
    output = tmp_path / "plan"
    plan = create_plan(universe, universe_sha, base, output, shard_size=shard_size)
    return plan, output, identifiers


def _refresh_checkpoint_hash(value: dict) -> None:
    body = {key: item for key, item in value.items() if key != "tb4_certificate_sha256"}
    value["tb4_certificate_sha256"] = hashlib.sha256(workflow.canonical_json(body)).hexdigest()


def _verify_artifact_root_regressions(
    checkpoint: dict,
    output: Path,
    *,
    multigen: bool,
) -> None:
    validator = validate_multigen_sharded_checkpoint if multigen else validate_sharded_checkpoint
    copied_output = output.with_name(f"{output.name}-copy")
    shutil.copytree(output, copied_output)
    copied_checkpoint = json.loads((copied_output / "checkpoint.json").read_text())
    copied_records = [
        copied_checkpoint["artifacts"]["results"],
        copied_checkpoint["artifacts"]["audit_summary"],
        copied_checkpoint["artifacts"]["deployment_spec"],
        *(
            copied_checkpoint["artifacts"]["proxy_policies"]
            if multigen
            else [copied_checkpoint["artifacts"]["proxy_policy"]]
        ),
    ]
    assert all(Path(record["path"]).parent == output for record in copied_records)
    assert all((copied_output / Path(record["path"]).name).is_file() for record in copied_records)
    assert all(
        stat.S_IMODE((copied_output / Path(record["path"]).name).stat().st_mode) == 0o600 for record in copied_records
    )

    with pytest.raises(ShardWorkflowError, match="sharded_checkpoint_artifacts_invalid"):
        validator(
            copied_checkpoint,
            deployment_id="deployment-test",
            artifact_root=copied_output,
        )

    redirects: list[tuple[str, str]] = [
        ("results", "results.jsonl"),
        ("audit_summary", "audit_summary.json"),
        ("deployment_spec", "deployment_spec_policy.json"),
    ]
    if multigen:
        redirects.extend(
            (f"proxy_policy:{item['policy_sha256']}", Path(item["path"]).name)
            for item in checkpoint["artifacts"]["proxy_policies"]
        )
    else:
        redirects.append(("proxy_policy", "proxy_policy.json"))
    for target, filename in redirects:
        redirected = json.loads(json.dumps(checkpoint))
        if target.startswith("proxy_policy:"):
            policy_sha256 = target.removeprefix("proxy_policy:")
            for item in redirected["artifacts"]["proxy_policies"]:
                if item["policy_sha256"] == policy_sha256:
                    item["path"] = str(copied_output / filename)
            for record in redirected["shards"]:
                if record["proxy_policy_sha256"] == policy_sha256:
                    record["proxy_policy_artifact"]["path"] = str(copied_output / filename)
        else:
            redirected["artifacts"][target]["path"] = str(copied_output / filename)
        _refresh_checkpoint_hash(redirected)
        with pytest.raises(ShardWorkflowError, match="sharded_checkpoint_artifacts_invalid"):
            validator(
                redirected,
                deployment_id="deployment-test",
                artifact_root=output,
            )

    lexical_alias = json.loads(json.dumps(checkpoint))
    lexical_alias["artifacts"]["results"]["path"] = str(output / ".." / output.name / "results.jsonl")
    _refresh_checkpoint_hash(lexical_alias)
    assert (
        validator(
            lexical_alias,
            deployment_id="deployment-test",
            artifact_root=output,
        )["certificate_sha256"]
        == lexical_alias["tb4_certificate_sha256"]
    )

    root_alias = output.with_name(f"{output.name}-alias")
    root_alias.symlink_to(output, target_is_directory=True)
    assert (
        validator(
            checkpoint,
            deployment_id="deployment-test",
            artifact_root=root_alias,
        )["certificate_sha256"]
        == checkpoint["tb4_certificate_sha256"]
    )

    result_alias = output.with_name(f"{output.name}-results-link.jsonl")
    result_alias.symlink_to(output / "results.jsonl")
    linked_result = json.loads(json.dumps(checkpoint))
    linked_result["artifacts"]["results"]["path"] = str(result_alias)
    _refresh_checkpoint_hash(linked_result)
    with pytest.raises(ShardWorkflowError, match="sharded_checkpoint_results_unreadable"):
        validator(
            linked_result,
            deployment_id="deployment-test",
            artifact_root=output,
        )


def test_plan_is_private_deterministic_and_exact(tmp_path: Path):
    plan, output, identifiers = _make_plan(tmp_path)
    loaded, shards = load_plan(output / "plan.json")

    assert plan["plan_sha256"] == loaded["plan_sha256"]
    assert len(shards) == 17
    assert [shard.task_count for shard in shards] == [4] * 16 + [2]
    assert set().union(*(set(shard.tasks) for shard in shards)) == set(identifiers)
    assert sum(shard.task_count for shard in shards) == 66
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())
    plan_text = (output / "plan.json").read_text()
    assert not any(identifier in plan_text for identifier in identifiers)


def test_plan_rejects_non_private_universe(tmp_path: Path):
    universe, universe_sha, _ = _universe(tmp_path)
    universe.chmod(0o644)
    base = _base_config(tmp_path, universe, universe_sha)

    with pytest.raises(ShardWorkflowError, match="universe_manifest_not_private"):
        create_plan(universe, universe_sha, base, tmp_path / "plan", shard_size=4)


def test_current_kimi_base_config_can_seed_a_private_plan(tmp_path: Path):
    workflow_dir = Path(workflow.__file__).resolve().parent
    base = workflow_dir / "configs/eval/tb4_kimi_k3_max_miniswe.toml"
    config = tomllib.loads(base.read_text())
    source_manifest = Path(config["taskset"]["task_file"]).resolve(strict=True)
    universe = tmp_path / "private-universe.txt"
    shutil.copyfile(source_manifest, universe)
    universe.chmod(0o600)

    plan = create_plan(
        universe,
        config["taskset"]["task_file_sha256"],
        base,
        tmp_path / "plan",
        shard_size=4,
    )
    assert plan["universe"]["task_count"] == 66
    assert plan["shard_count"] == 17


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("timeout", "setup", 3_599),
        ("timeout", "rollout", 28_800),
        ("timeout", "finalize", 3_599),
        ("timeout", "scoring", 21_599),
        ("client", "connect_timeout", 119),
        ("harness.runtime", "session_timeout", 32_400),
    ],
)
def test_full_tb4_base_config_rejects_weakened_or_smoke_timeout_profile(
    tmp_path: Path,
    section: str,
    key: str,
    value: int,
) -> None:
    universe, universe_sha, _ = _universe(tmp_path)
    config = tomllib.loads(_base_config(tmp_path, universe, universe_sha).read_text())
    target = config["harness"]["runtime"] if section == "harness.runtime" else config[section]
    target[key] = value

    with pytest.raises(ShardWorkflowError, match="^base_config_contract_invalid$"):
        _validate_base_config(config, universe_sha)


def test_full_tb4_base_config_rejects_complete_smoke_timeout_pair(tmp_path: Path) -> None:
    universe, universe_sha, _ = _universe(tmp_path)
    config = tomllib.loads(_base_config(tmp_path, universe, universe_sha).read_text())
    config["timeout"]["rollout"] = 28_800
    config["harness"]["runtime"]["session_timeout"] = 32_400

    with pytest.raises(ShardWorkflowError, match="^base_config_contract_invalid$"):
        _validate_base_config(config, universe_sha)


@pytest.mark.parametrize(
    "rollout_retries",
    [
        {"max_retries": 1, "include": ["ProviderError", "SandboxError", "TunnelError", "InterceptionError"]},
        {"max_retries": 2, "include": ["ProviderError", "SandboxError", "TunnelError"]},
        {
            "max_retries": 2,
            "include": ["ProviderError", "SandboxError", "TunnelError", "HarnessError"],
        },
        {
            "max_retries": 2,
            "include": [
                "ProviderError",
                "SandboxError",
                "TunnelError",
                "InterceptionError",
                "UnknownError",
            ],
        },
    ],
)
def test_full_tb4_base_config_rejects_broad_missing_or_swapped_retries(
    tmp_path: Path,
    rollout_retries: dict[str, object],
) -> None:
    universe, universe_sha, _ = _universe(tmp_path)
    config = tomllib.loads(_base_config(tmp_path, universe, universe_sha).read_text())
    config["retries"]["rollout"] = rollout_retries

    with pytest.raises(ShardWorkflowError, match="^base_config_contract_invalid$"):
        _validate_base_config(config, universe_sha)


def test_load_plan_rejects_artifact_tamper(tmp_path: Path):
    _plan, output, _ = _make_plan(tmp_path)
    manifest = output / "shard-000.tasks.txt"
    manifest.write_bytes(manifest.read_bytes() + b"tamper\n")
    manifest.chmod(0o600)

    with pytest.raises(ShardWorkflowError, match="plan_artifact_sha256_mismatch"):
        load_plan(output / "plan.json")


def test_config_semantics_ignore_only_selection_and_runtime_endpoint(tmp_path: Path):
    universe, universe_sha, _ = _universe(tmp_path)
    config = tomllib.loads(_base_config(tmp_path, universe, universe_sha).read_text())
    changed_selection = json.loads(json.dumps(config))
    changed_selection["num_tasks"] = 1
    changed_selection["output_dir"] = "/private/run"
    changed_selection["taskset"]["task_file"] = "/private/shard"
    changed_selection["taskset"]["task_file_sha256"] = "0" * 64
    changed_selection["client"]["base_url"] = "http://replacement.invalid/v1"
    assert _config_semantics_sha256(config) == _config_semantics_sha256(changed_selection)

    changed_semantics = json.loads(json.dumps(changed_selection))
    changed_semantics["max_concurrent"] = 3
    assert _config_semantics_sha256(config) != _config_semantics_sha256(changed_semantics)


def test_scan_results_requires_exactly_one_row_per_planned_case(tmp_path: Path):
    identifiers = _identifiers()[:2]
    results = tmp_path / "results.jsonl"
    rows = [{"id": f"trace-{index}", "task": {"slug": identifier}} for index, identifier in enumerate(identifiers)]
    results.write_text("".join(json.dumps(row) + "\n" for row in rows))
    digest, trace_ids, count = _scan_results(results, frozenset(identifiers))
    assert digest == hashlib.sha256(results.read_bytes()).hexdigest()
    assert len(trace_ids) == count == 2

    results.write_text(json.dumps(rows[0]) + "\n" + json.dumps(rows[0]) + "\n")
    with pytest.raises(ShardWorkflowError, match="shard_trace_identity_invalid"):
        _scan_results(results, frozenset(identifiers))


def test_certify_shard_uses_validated_snapshot_after_live_proxy_path_is_obsolete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, plan_dir, _identifiers = _make_plan(tmp_path, shard_size=1)
    _loaded, shards = load_plan(plan_dir / "plan.json")
    shard = shards[0]
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    receipt_path = run_dir / "route_guard_success.json"
    _private_write(receipt_path, b"{}\n")
    identity_path = run_dir / "eval_run_identity.json"
    _private_write(identity_path, b"{}\n")
    results_path = run_dir / "results.jsonl"
    results_path.write_text(json.dumps({"id": "trace-0", "task": {"slug": next(iter(shard.tasks))}}) + "\n")
    results_sha256 = hashlib.sha256(results_path.read_bytes()).hexdigest()

    deployment_spec = tmp_path / "deployment-spec.yaml"
    deployment_spec.write_text("spec:\n  num_endpoints: 1\n")
    deployment_spec_sha256 = hashlib.sha256(deployment_spec.read_bytes()).hexdigest()
    snapshot = tmp_path / "proxy-config-snapshot.yaml"
    route = "http://worker-0.invalid:8000/v1"
    snapshot.write_text(
        "model_list:\n"
        "  - model_name: kimi\n"
        "    litellm_params:\n"
        "      model: openai/Kimi-K3\n"
        f"      api_base: {route}\n"
        "litellm_settings:\n"
        "  request_timeout: 43200\n"
        "  num_retries: 0\n"
    )
    snapshot.chmod(0o600)
    snapshot_sha256 = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    obsolete_live_path = tmp_path / "removed-live-proxy-config.yaml"
    assert not obsolete_live_path.exists()
    proxy_policy = {
        "schema_version": 1,
        "request_timeout": 43_200,
        "num_retries": 0,
        "proxy_litellm_config": {
            "path": str(obsolete_live_path),
            "sha256": snapshot_sha256,
        },
    }
    route_generation = {
        "routes": [
            {
                "backend_sha256": f"backend-sha256:{hashlib.sha256(route.encode()).hexdigest()}",
            }
        ]
    }
    identity = {
        "source": {"revision": "1" * 40},
        "dataset": {"path": str(tmp_path / "dataset")},
        "contract": {"model": "Kimi-K3"},
        "inputs": {
            "task_file": {
                "path": str(shard.task_manifest),
                "sha256": shard.task_manifest_sha256,
                "count": shard.task_count,
            }
        },
        "config": {
            "source": {"path": str(shard.config), "sha256": shard.config_sha256},
            "resolved": {"path": str(shard.config), "sha256": shard.config_sha256},
        },
        "execution": {
            "rollout_concurrency": 4,
            "multiplex": 4,
            "http_max_connections": 4,
            "http_max_keepalive_connections": 4,
            "vmvm_environment": {"lease_start_concurrency": 2},
        },
        "deployment": {
            "id": "deployment-test",
            "spec": {"path": str(deployment_spec), "sha256": deployment_spec_sha256},
            "readiness_checkpoint": {},
            "endpoint": {},
            "serving_route_generation": route_generation,
            "routing": {},
            "proxy_policy": proxy_policy,
        },
        "role": "tb4",
    }
    envelope = {"identity": identity, "eval_run_identity_sha256": "e" * 64}
    receipt = {
        "artifacts": {
            "eval_run_identity": {"path": str(identity_path), "sha256": "a" * 64},
            "results": {"path": str(results_path), "sha256": results_sha256},
        },
        "guard_success_receipt_sha256": "b" * 64,
    }

    monkeypatch.setattr(guard_success_receipt, "load_guard_success_receipt", lambda _path: receipt)
    monkeypatch.setattr(guard_success_receipt, "validate_guard_success_linkage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(eval_run_identity, "load_eval_run_identity", lambda *_args, **_kwargs: envelope)

    certified = workflow._certify_shard(
        receipt_path,
        {shard.task_manifest_sha256: shard},
        expected_semantics_sha256=plan["base_config"]["semantics_sha256"],
        proxy_config_snapshot=snapshot,
    )

    assert certified.proxy_config == snapshot.resolve()
    assert certified.proxy_config_sha256 == snapshot_sha256
    assert certified.identity_semantics["deployment"]["proxy_policy"]["proxy_litellm_config"]["path"] == str(
        obsolete_live_path
    )


def test_writer_lock_is_acquired_once_and_rejects_an_active_writer(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    lock_path = run_dir / ".writer.lock"
    lock_path.write_bytes(b"")
    with _hold_writer_lock(run_dir):
        pass
    with lock_path.open("rb") as active_writer:
        fcntl.flock(active_writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ShardWorkflowError, match="shard_still_running"):
            with _hold_writer_lock(run_dir):
                pass


def test_merge_publishes_only_complete_certified_partition(tmp_path: Path, monkeypatch):
    plan, plan_dir, identifiers = _make_plan(tmp_path, shard_size=22)
    _loaded, shards = load_plan(plan_dir / "plan.json")
    dataset = tmp_path / "dataset"
    for identifier in identifiers:
        task = dataset / identifier
        task.mkdir(parents=True)
        (task / "task.toml").write_text("")
        (task / "instruction.md").write_text("")

    receipt_paths: list[Path] = []
    by_receipt: dict[Path, CertifiedShard] = {}
    deployment_spec = tmp_path / "deployment" / "spec.yaml"
    deployment_spec.parent.mkdir()
    deployment_spec.write_text(
        "spec:\n  proxy:\n    config:\n      request_timeout: 43200\n      num_retries: 0\n"
        "credential_sibling: must-not-be-copied\n"
    )
    proxy_config = deployment_spec.parent / "proxy_litellm_config.yaml"
    proxy_config.write_text("litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\n")
    semantics = {
        "source": {"same": True},
        "dataset": {"path": str(dataset)},
        "contract": {"same": True},
        "execution": {"same": True},
        "resolved_config_semantics_sha256": "a" * 64,
        "deployment": {
            "id": "deployment-test",
            "spec_sha256": hashlib.sha256(deployment_spec.read_bytes()).hexdigest(),
            "routing": {"same": True},
            "proxy_policy": {
                "schema_version": 1,
                "request_timeout": 43_200,
                "num_retries": 0,
                "proxy_litellm_config": {
                    "path": str(proxy_config.resolve()),
                    "sha256": hashlib.sha256(proxy_config.read_bytes()).hexdigest(),
                },
            },
        },
    }
    for shard in shards:
        run_dir = tmp_path / f"run-{shard.index:03d}"
        run_dir.mkdir()
        (run_dir / ".writer.lock").write_bytes(b"")
        receipt = run_dir / "route_guard_success.json"
        _private_write(receipt, b"{}\n")
        results = run_dir / "results.jsonl"
        rows = [
            {"id": f"trace-{shard.index:03d}-{offset:03d}", "task": {"slug": identifier}}
            for offset, identifier in enumerate(sorted(shard.tasks))
        ]
        results.write_text("".join(json.dumps(row) + "\n" for row in rows))
        results_sha = hashlib.sha256(results.read_bytes()).hexdigest()
        certified = CertifiedShard(
            spec=shard,
            run_dir=run_dir,
            results=results,
            results_sha256=results_sha,
            results_count=shard.task_count,
            success_receipt=receipt.resolve(),
            success_receipt_sha256=hashlib.sha256(f"receipt-{shard.index}".encode()).hexdigest(),
            success_receipt_file_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
            eval_run_identity_sha256=hashlib.sha256(f"identity-{shard.index}".encode()).hexdigest(),
            route_generation_sha256=hashlib.sha256(f"generation-{shard.index}".encode()).hexdigest(),
            endpoint_binding_sha256="b" * 64,
            expected_routes=1,
            trace_ids=frozenset(row["id"] for row in rows),
            identity_semantics=semantics,
            deployment_spec=deployment_spec.resolve(),
            deployment_spec_sha256=hashlib.sha256(deployment_spec.read_bytes()).hexdigest(),
            proxy_config=proxy_config.resolve(),
            proxy_config_sha256=hashlib.sha256(proxy_config.read_bytes()).hexdigest(),
        )
        receipt_paths.append(receipt)
        by_receipt[receipt.resolve()] = certified

    historical_snapshots: list[tuple[Path | None, Path | None]] = []

    def certify(
        path: Path,
        _mapping: object,
        *,
        expected_semantics_sha256: str,
        deployment_spec_snapshot: Path | None = None,
        proxy_policy_snapshot: Path | None = None,
        proxy_config_snapshot: Path | None = None,
    ) -> CertifiedShard:
        assert expected_semantics_sha256
        assert proxy_config_snapshot is None
        historical_snapshots.append((deployment_spec_snapshot, proxy_policy_snapshot))
        return by_receipt[path.resolve()]

    monkeypatch.setattr(workflow, "_certify_shard", certify)
    monkeypatch.setattr(
        workflow,
        "_run_full_audit",
        lambda *_args, **_kwargs: (
            {
                "ok": True,
                "observed_traces": 66,
                "supported_tasks": 63,
                "observed_unsupported_tasks": ["opaque"] * 3,
                "supported_passes": 4,
                "trace_failures": 0,
                "supported_trace_failures": 0,
                "unsupported_trace_failures": 0,
                "global_problems": [],
                "supported_pass_rate": 4 / 63,
                "all_task_pass_rate": 4 / 66,
            },
            False,
        ),
    )
    output = tmp_path / "merged"
    receipt = merge_shards(
        plan_dir / "plan.json",
        receipt_paths,
        output_dir=output,
        dataset_dir=dataset,
    )
    assert receipt["combined_trace_count"] == 66
    assert receipt["distinct_route_generations"] == len(shards)
    assert len((output / "results.jsonl").read_text().splitlines()) == 66
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())
    deployment_spec.write_text("spec:\n  num_endpoints: 24\n")
    proxy_config.write_text("litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\n  model_list: []\n")
    validated = validate_sharded_checkpoint(
        receipt,
        deployment_id="deployment-test",
        artifact_root=output,
    )
    assert validated["sharded"] is True
    assert validated["shard_count"] == len(shards)
    assert historical_snapshots[: len(shards)] == [(None, None)] * len(shards)
    assert all(spec == output / "deployment_spec_policy.json" for spec, _ in historical_snapshots[len(shards) :])
    assert b"must-not-be-copied" not in (output / "deployment_spec_policy.json").read_bytes()
    assert all(proxy == output / "proxy_policy.json" for _, proxy in historical_snapshots[len(shards) :])
    assert (
        mobius_launch_certificate._validate_tb4_checkpoint(
            receipt,
            "deployment-test",
            {},
            output,
        )
        == validated
    )
    _verify_artifact_root_regressions(receipt, output, multigen=False)

    weakened_policy = json.loads(json.dumps(receipt))
    weakened_policy["audit_policy"]["require_request_graph_match"] = False
    unsigned = dict(weakened_policy)
    unsigned.pop("tb4_certificate_sha256")
    weakened_policy["tb4_certificate_sha256"] = hashlib.sha256(workflow.canonical_json(unsigned)).hexdigest()
    with pytest.raises(ShardWorkflowError, match="sharded_checkpoint_policy_invalid"):
        validate_sharded_checkpoint(
            weakened_policy,
            deployment_id="deployment-test",
            artifact_root=output,
        )

    tampered = json.loads(json.dumps(receipt))
    tampered["shards"][0]["route_generation_sha256"] = "0" * 64
    unsigned = dict(tampered)
    unsigned.pop("tb4_certificate_sha256")
    tampered["tb4_certificate_sha256"] = hashlib.sha256(workflow.canonical_json(unsigned)).hexdigest()
    with pytest.raises(ShardWorkflowError, match="sharded_checkpoint_shard_mismatch"):
        validate_sharded_checkpoint(
            tampered,
            deployment_id="deployment-test",
            artifact_root=output,
        )

    proxy_policy_snapshot = output / "proxy_policy.json"
    proxy_policy_snapshot.write_bytes(proxy_policy_snapshot.read_bytes() + b"{}\n")
    with pytest.raises(
        ShardWorkflowError,
        match="sharded_checkpoint_proxy_policy_sha256_mismatch",
    ):
        validate_sharded_checkpoint(
            receipt,
            deployment_id="deployment-test",
            artifact_root=output,
        )


def test_multigen_merge_and_checkpoint_allow_distinct_proxy_config_snapshots(tmp_path: Path, monkeypatch):
    _plan, plan_dir, identifiers = _make_plan(tmp_path, shard_size=1)
    _loaded, shards = load_plan(plan_dir / "plan.json")
    dataset = tmp_path / "dataset"
    for identifier in identifiers:
        task = dataset / identifier
        task.mkdir(parents=True)
        (task / "task.toml").write_text("")
        (task / "instruction.md").write_text("")

    deployment_spec = tmp_path / "deployment" / "spec.yaml"
    deployment_spec.parent.mkdir()
    deployment_spec.write_text("spec:\n  proxy:\n    config:\n      request_timeout: 43200\n      num_retries: 0\n")
    deployment_spec_sha256 = hashlib.sha256(deployment_spec.read_bytes()).hexdigest()
    live_proxy_config = tmp_path / "deployment" / "proxy_litellm_config.yaml"
    live_proxy_config.write_text("litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\n")
    proxy_a = tmp_path / "generation-a" / "proxy_litellm_config.yaml"
    proxy_b = tmp_path / "generation-b" / "proxy_litellm_config.yaml"
    proxy_a.parent.mkdir()
    proxy_b.parent.mkdir()
    routes_a = ["http://generation-a-0.invalid/v1", "http://generation-a-1.invalid/v1"]
    routes_b = ["http://generation-b-0.invalid/v1", "http://generation-b-1.invalid/v1"]
    proxy_a.write_text(
        "model_list:\n"
        "  - model_name: kimi\n"
        "    litellm_params:\n"
        "      model: openai/Kimi-K3\n"
        f"      api_base: {routes_a[0]}\n"
        "  - model_name: kimi\n"
        "    litellm_params:\n"
        "      model: openai/Kimi-K3\n"
        f"      api_base: {routes_a[1]}\n"
        "litellm_settings:\n"
        "  request_timeout: 43200\n"
        "  num_retries: 0\n"
    )
    proxy_b.write_text(
        "model_list:\n"
        "  - model_name: kimi\n"
        "    litellm_params:\n"
        "      model: openai/Kimi-K3\n"
        f"      api_base: {routes_b[0]}\n"
        "  - model_name: kimi\n"
        "    litellm_params:\n"
        "      model: openai/Kimi-K3\n"
        f"      api_base: {routes_b[1]}\n"
        "litellm_settings:\n"
        "  request_timeout: 43200\n"
        "  num_retries: 0\n"
    )
    proxy_a.chmod(0o600)
    proxy_b.chmod(0o600)
    proxy_a_sha256 = hashlib.sha256(proxy_a.read_bytes()).hexdigest()
    proxy_b_sha256 = hashlib.sha256(proxy_b.read_bytes()).hexdigest()
    assert proxy_a_sha256 != proxy_b_sha256

    def semantics(proxy_config: Path, proxy_config_sha256: str) -> dict:
        return {
            "source": {"same": True},
            "dataset": {"path": str(dataset)},
            "contract": {"same": True},
            "execution": {"same": True},
            "resolved_config_semantics_sha256": "a" * 64,
            "deployment": {
                "id": "deployment-test",
                "spec_sha256": deployment_spec_sha256,
                "routing": {"deployment_id": "deployment-test", "headers": {}},
                "proxy_policy": {
                    "schema_version": 1,
                    "request_timeout": 43_200,
                    "num_retries": 0,
                    "proxy_litellm_config": {
                        "path": str(live_proxy_config.resolve()),
                        "sha256": proxy_config_sha256,
                    },
                },
            },
        }

    receipt_paths: list[Path] = []
    by_receipt: dict[Path, CertifiedShard] = {}
    for shard in shards:
        proxy_config = proxy_a if shard.index < 33 else proxy_b
        proxy_config_sha256 = proxy_a_sha256 if shard.index < 33 else proxy_b_sha256
        route_urls = routes_a if shard.index < 33 else routes_b
        route_generation = {
            "routes": [
                {
                    "backend_sha256": f"backend-sha256:{hashlib.sha256(url.encode()).hexdigest()}",
                }
                for url in route_urls
            ]
        }
        run_dir = tmp_path / f"run-{shard.index:03d}"
        run_dir.mkdir()
        (run_dir / ".writer.lock").write_bytes(b"")
        receipt = run_dir / "route_guard_success.json"
        _private_write(receipt, b"{}\n")
        results = run_dir / "results.jsonl"
        rows = [
            {"id": f"trace-{shard.index:03d}-{offset:03d}", "task": {"slug": identifier}}
            for offset, identifier in enumerate(sorted(shard.tasks))
        ]
        results.write_text("".join(json.dumps(row) + "\n" for row in rows))
        results_sha = hashlib.sha256(results.read_bytes()).hexdigest()
        certified = CertifiedShard(
            spec=shard,
            run_dir=run_dir,
            results=results,
            results_sha256=results_sha,
            results_count=shard.task_count,
            success_receipt=receipt.resolve(),
            success_receipt_sha256=hashlib.sha256(f"receipt-{shard.index}".encode()).hexdigest(),
            success_receipt_file_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
            eval_run_identity_sha256=hashlib.sha256(f"identity-{shard.index}".encode()).hexdigest(),
            route_generation_sha256=hashlib.sha256(workflow.canonical_json(route_generation)).hexdigest(),
            endpoint_binding_sha256=hashlib.sha256(f"endpoint-{shard.index // 33}".encode()).hexdigest(),
            expected_routes=2,
            trace_ids=frozenset(row["id"] for row in rows),
            identity_semantics=semantics(proxy_config, proxy_config_sha256),
            deployment_spec=deployment_spec.resolve(),
            deployment_spec_sha256=deployment_spec_sha256,
            proxy_config=live_proxy_config.resolve(),
            proxy_config_sha256=proxy_config_sha256,
            route_generation=route_generation,
        )
        receipt_paths.append(receipt)
        by_receipt[receipt.resolve()] = certified

    def certify(
        path: Path,
        _mapping: object,
        *,
        expected_semantics_sha256: str,
        deployment_spec_snapshot: Path | None = None,
        proxy_policy_snapshot: Path | None = None,
        proxy_config_snapshot: Path | None = None,
    ) -> CertifiedShard:
        assert expected_semantics_sha256
        if deployment_spec_snapshot is not None:
            assert deployment_spec_snapshot.name == "deployment_spec_policy.json"
        if proxy_policy_snapshot is not None:
            assert proxy_policy_snapshot.name.startswith("proxy_policy_")
        if proxy_config_snapshot is not None:
            assert proxy_config_snapshot in {
                proxy_a.resolve(),
                proxy_b.resolve(),
                bad_proxy_b.resolve() if bad_proxy_b.exists() else proxy_b.resolve(),
            }
        return by_receipt[path.resolve()]

    monkeypatch.setattr(workflow, "_certify_shard", certify)
    monkeypatch.setattr(
        workflow,
        "_run_full_audit",
        lambda *_args, **_kwargs: (
            {
                "ok": True,
                "observed_traces": 66,
                "supported_tasks": 63,
                "observed_unsupported_tasks": ["opaque"] * 3,
                "supported_passes": 4,
                "trace_failures": 0,
                "supported_trace_failures": 0,
                "unsupported_trace_failures": 0,
                "global_problems": [],
                "supported_pass_rate": 4 / 63,
                "all_task_pass_rate": 4 / 66,
            },
            False,
        ),
    )

    with pytest.raises(ShardWorkflowError, match="shard_identity_semantics_mismatch"):
        merge_shards(
            plan_dir / "plan.json",
            receipt_paths,
            output_dir=tmp_path / "strict",
            dataset_dir=dataset,
        )

    bad_proxy_b = tmp_path / "generation-b-bad" / "proxy_litellm_config.yaml"
    bad_proxy_b.parent.mkdir()
    bad_proxy_b.write_text(
        "model_list:\n"
        "  - model_name: kimi\n"
        "    litellm_params:\n"
        "      model: openai/Kimi-K3\n"
        f"      api_base: {routes_b[0]}\n"
        "  - model_name: changed-non-route-field\n"
        "    litellm_params:\n"
        "      model: openai/Kimi-K3\n"
        f"      api_base: {routes_b[1]}\n"
        "litellm_settings:\n"
        "  request_timeout: 43200\n"
        "  num_retries: 0\n"
    )
    bad_proxy_b.chmod(0o600)
    bad_proxy_b_sha256 = hashlib.sha256(bad_proxy_b.read_bytes()).hexdigest()
    original_by_receipt = dict(by_receipt)
    try:
        for path, certified in original_by_receipt.items():
            if certified.spec.index >= 33:
                by_receipt[path] = replace(
                    certified,
                    identity_semantics=semantics(bad_proxy_b, bad_proxy_b_sha256),
                    proxy_config=live_proxy_config.resolve(),
                    proxy_config_sha256=bad_proxy_b_sha256,
                )
        with pytest.raises(ShardWorkflowError, match="worker_rotation_proxy_config_mismatch"):
            merge_multigen_shards(
                plan_dir / "plan.json",
                receipt_paths,
                output_dir=tmp_path / "multigen-bad",
                dataset_dir=dataset,
                proxy_config_snapshots={
                    path.resolve(): (
                        proxy_a.resolve() if by_receipt[path.resolve()].spec.index < 33 else bad_proxy_b.resolve()
                    )
                    for path in receipt_paths
                },
            )
    finally:
        by_receipt.clear()
        by_receipt.update(original_by_receipt)

    output = tmp_path / "multigen"
    receipt = merge_multigen_shards(
        plan_dir / "plan.json",
        receipt_paths,
        output_dir=output,
        dataset_dir=dataset,
        proxy_config_snapshots={
            path.resolve(): (proxy_a.resolve() if by_receipt[path.resolve()].spec.index < 33 else proxy_b.resolve())
            for path in receipt_paths
        },
    )

    assert receipt["schema_version"] == 3
    assert receipt["deployment"]["proxy_policy_sha256s"] == sorted(
        {
            hashlib.sha256(
                workflow.canonical_json(semantics(proxy_a, proxy_a_sha256)["deployment"]["proxy_policy"])
            ).hexdigest(),
            hashlib.sha256(
                workflow.canonical_json(semantics(proxy_b, proxy_b_sha256)["deployment"]["proxy_policy"])
            ).hexdigest(),
        }
    )
    assert len(receipt["artifacts"]["proxy_policies"]) == 2
    assert {record["proxy_policy_sha256"] for record in receipt["shards"]} == set(
        receipt["deployment"]["proxy_policy_sha256s"]
    )
    live_proxy_config.write_text("litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\n  rotated: true\n")
    validated = validate_multigen_sharded_checkpoint(
        receipt,
        deployment_id="deployment-test",
        artifact_root=output,
    )
    assert validated["sharded"] is True
    assert validated["shard_count"] == 66
    assert validated["proxy_policy_sha256s"] == receipt["deployment"]["proxy_policy_sha256s"]
    _verify_artifact_root_regressions(receipt, output, multigen=True)


def test_merge_rejects_missing_success_receipt_before_output(tmp_path: Path):
    _plan, plan_dir, _ = _make_plan(tmp_path, shard_size=22)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    output = tmp_path / "merged"

    with pytest.raises(ShardWorkflowError, match="success_receipt_count_mismatch"):
        merge_shards(
            plan_dir / "plan.json",
            [],
            output_dir=output,
            dataset_dir=dataset,
        )
    assert not output.exists()
