from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

import pytest

SERVER_DIR = Path(__file__).parents[1] / "configs" / "eval" / "servers" / "cpu-132-021_8103"
sys.path.insert(0, str(SERVER_DIR))

import validate_launch as validate_launch_module  # noqa: E402
from validate_launch import (  # noqa: E402
    EXPECTED_CONFIG_FILE,
    EXPECTED_CONFIG_SHA256,
    EXPECTED_HTTP_CONCURRENCY,
    EXPECTED_PROXY_NUM_RETRIES,
    EXPECTED_PROXY_REQUEST_TIMEOUT,
    EXPECTED_PYDANTIC_CONFIG_REVISION,
    EXPECTED_RENDERERS_REVISION,
    EXPECTED_ROLLOUT_CONCURRENCY,
    EXPECTED_ROUTES,
    EXPECTED_VERIFIERS_REVISION,
    EXPECTED_WAITING_REQUESTS,
    PROFILES,
    TB4_CONFIG_FILE,
    TB4_CONFIG_SHA256,
    TB4_DATASET_DIRECTORY_COUNT,
    TB4_DATASET_FILE_COUNT,
    TB4_DATASET_TREE_SHA256,
    HttpResponse,
    ProxyMetadata,
    SharedKimiValidationError,
    _dataset_tree_identity,
    _expected_resolved_config,
    _require_clean_git_worktree,
    _validate_common_eval_contract,
    main,
    validate_deployment,
    validate_eval_config,
    validate_resume,
    validate_resume_location,
    validate_runtime_metadata,
)

GOOD_PROXY_LITELLM_CONFIG = b"""\
model_list: []
general_settings: {}
router_settings: {}
litellm_settings:
  request_timeout: 7200
  num_retries: 0
"""


class FakeMetadataTransport:
    def __init__(self, *, healthy: int = EXPECTED_ROUTES, unhealthy: int = 0) -> None:
        self.healthy = healthy
        self.unhealthy = unhealthy
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        self.calls.append((url, headers, timeout))
        if url.endswith("/v1/models"):
            payload = {"data": [{"id": "Kimi-K3"}]}
        else:
            payload = {
                "healthy_count": self.healthy,
                "unhealthy_count": self.unhealthy,
            }
        return HttpResponse(200, json.dumps(payload).encode())


def _deployment(tmp_path: Path) -> tuple[Path, Path, str, str]:
    root = tmp_path / "shared-kimi-k3"
    endpoints = root / "endpoints"
    endpoints.mkdir(parents=True)
    spec = b"fixture deployment spec\n"
    (root / "spec.yaml").write_bytes(spec)
    (root / "proxy_config.json").write_text(
        json.dumps(
            {
                "pixi_env": "proxy-litellm-x86/test",
                "sticky": True,
                "sticky_ttl": 14_400,
            }
        )
    )
    (root / "proxy_litellm_config.yaml").write_bytes(GOOD_PROXY_LITELLM_CONFIG)
    proxy_url = "http://proxy.example:8103"
    proxy_info = root / "proxy_info.json"
    proxy_info.write_text(
        json.dumps(
            {
                "url": proxy_url,
                "api_key": "test-secret-key",
                "model": "Kimi-K3",
                "host": "proxy.example",
                "port": 8103,
                "proxy_jobid": "12345",
                "extras": {
                    "proxy_type": "litellm",
                    "prometheus_port": 8103,
                    "sticky": True,
                    "sticky_ttl": 14_400,
                    "redis_port": 39191,
                },
            }
        )
    )
    for index in range(EXPECTED_ROUTES):
        (endpoints / f"{10_000 + index}.json").write_text(
            json.dumps(
                {
                    "host": f"worker-{index}",
                    "port": 19_000 + index,
                    "started_at": "2026-09-16T20:21:47Z",
                }
            )
        )
    return root, proxy_info, hashlib.sha256(spec).hexdigest(), proxy_url


def _toml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise AssertionError(f"unsupported fixture value: {type(value).__name__}")


def _toml_document(value: Mapping[str, object]) -> str:
    lines: list[str] = []

    def render(table: Mapping[str, object], prefix: str) -> None:
        if prefix:
            lines.append(f"[{prefix}]")
        for key, item in table.items():
            if not isinstance(item, dict):
                lines.append(f"{key} = {_toml_scalar(item)}")
        lines.append("")
        for key, item in table.items():
            if isinstance(item, dict):
                render(item, f"{prefix}.{key}" if prefix else key)

    render(value, "")
    return "\n".join(lines)


def _resume_fixture(tmp_path: Path, *, profile_name: str = "mobius") -> tuple[Path, Path, ProxyMetadata]:
    project = Path(__file__).resolve().parents[4]
    profile = PROFILES[profile_name]
    resume = (tmp_path / "resume").resolve()
    inputs = resume / "inputs"
    inputs.mkdir(parents=True)

    source_config = project / profile.config_file
    source_snapshot = inputs / "source_config.toml"
    source_snapshot.write_bytes(source_config.read_bytes())
    task_source = project / profile.task_file
    task_snapshot = inputs / "task_file.txt"
    task_snapshot.write_bytes(task_source.read_bytes())

    manifest: dict[str, dict[str, str]] = {
        "config": {
            "source": str(source_config),
            "snapshot": str(source_snapshot),
            "sha256": profile.config_sha256,
        },
        "task_file": {
            "source": str(task_source),
            "snapshot": str(task_snapshot),
            "sha256": profile.task_sha256,
        },
    }
    if profile.image_manifest is not None and profile.image_sha256 is not None:
        image_source = Path(profile.image_manifest)
        image_snapshot = inputs / "image_manifest.json"
        image_snapshot.write_bytes(image_source.read_bytes())
        manifest["image_manifest"] = {
            "source": str(image_source),
            "snapshot": str(image_snapshot),
            "sha256": profile.image_sha256,
        }
    (inputs / "manifest.json").write_text(json.dumps(manifest))
    (resume / "config.toml").write_text(_toml_document(_expected_resolved_config(profile, resume)))

    project_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    proxy = ProxyMetadata(
        url="http://cpu-132-021:8103",
        api_key="test-secret-key",
        proxy_info_sha256="a" * 64,
        proxy_litellm_config_sha256="b" * 64,
    )
    provenance = {
        "prime_rl": project_revision,
        "verifiers": EXPECTED_VERIFIERS_REVISION,
        "renderers": EXPECTED_RENDERERS_REVISION,
        "pydantic_config": EXPECTED_PYDANTIC_CONFIG_REVISION,
        "eval_config_sha256": profile.config_sha256,
        "inference_base_url": "http://cpu-132-021:8103/v1",
        "inference_deployment_id": "",
        "inference_proxy_info_sha256": proxy.proxy_info_sha256,
        "inference_proxy_litellm_config_sha256": proxy.proxy_litellm_config_sha256,
        "dataset_tree_sha256": profile.dataset_tree_sha256 or "",
        "slurm_job_id": "12345",
        "approval_task_file_sha256": profile.task_sha256,
        "approval_task_count": str(profile.task_count),
    }
    (resume / "provenance.txt").write_text("".join(f"{key}={value}\n" for key, value in provenance.items()))
    return project, resume, proxy


def test_shared_kimi_deployment_and_runtime_metadata_pass(tmp_path: Path) -> None:
    root, proxy_info, spec_sha256, proxy_url = _deployment(tmp_path)

    proxy = validate_deployment(
        root,
        proxy_info,
        expected_spec_sha256=spec_sha256,
        expected_proxy_url=proxy_url,
    )
    transport = FakeMetadataTransport()
    validate_runtime_metadata(proxy, transport=transport)

    assert proxy.url == proxy_url
    assert proxy.proxy_info_sha256 == hashlib.sha256(proxy_info.read_bytes()).hexdigest()
    assert proxy.proxy_litellm_config_sha256 == hashlib.sha256(GOOD_PROXY_LITELLM_CONFIG).hexdigest()
    assert len(transport.calls) == 2
    assert all(call[1]["Authorization"] == "Bearer test-secret-key" for call in transport.calls)
    assert EXPECTED_ROLLOUT_CONCURRENCY == 64
    assert EXPECTED_HTTP_CONCURRENCY == EXPECTED_ROUTES == 24
    assert EXPECTED_WAITING_REQUESTS == 40
    assert EXPECTED_PROXY_REQUEST_TIMEOUT == 7_200
    assert EXPECTED_PROXY_NUM_RETRIES == 0


@pytest.mark.parametrize(
    ("policy", "error"),
    [
        (
            b"litellm_settings:\n  request_timeout: 600\n  num_retries: 2\n",
            "proxy_litellm_config_policy_mismatch",
        ),
        (
            b"litellm_settings:\n  request_timeout: 7200\n",
            "proxy_litellm_config_policy_mismatch",
        ),
        (
            b"litellm_settings:\n  request_timeout: '7200'\n  num_retries: 0\n",
            "proxy_litellm_config_policy_mismatch",
        ),
        (
            b"litellm_settings:\n  request_timeout: 7200\n  num_retries: false\n",
            "proxy_litellm_config_policy_mismatch",
        ),
        (
            b"litellm_settings:\n  request_timeout: [\n",
            "proxy_litellm_config_invalid",
        ),
        (
            b"litellm_settings:\n  request_timeout: 7200\n  request_timeout: 7200\n  num_retries: 0\n",
            "proxy_litellm_config_invalid",
        ),
    ],
)
def test_shared_kimi_proxy_policy_fails_closed(tmp_path: Path, policy: bytes, error: str) -> None:
    root, proxy_info, spec_sha256, proxy_url = _deployment(tmp_path)
    (root / "proxy_litellm_config.yaml").write_bytes(policy)

    with pytest.raises(SharedKimiValidationError, match=f"^{error}$") as captured:
        validate_deployment(
            root,
            proxy_info,
            expected_spec_sha256=spec_sha256,
            expected_proxy_url=proxy_url,
        )

    assert "test-secret-key" not in str(captured.value)
    assert policy.decode("utf-8") not in str(captured.value)


def test_shared_kimi_proxy_policy_digest_covers_full_file(tmp_path: Path) -> None:
    root, proxy_info, spec_sha256, proxy_url = _deployment(tmp_path)
    initial = validate_deployment(
        root,
        proxy_info,
        expected_spec_sha256=spec_sha256,
        expected_proxy_url=proxy_url,
    )
    changed_policy = GOOD_PROXY_LITELLM_CONFIG + b"# semantically inert digest change\n"
    (root / "proxy_litellm_config.yaml").write_bytes(changed_policy)

    changed = validate_deployment(
        root,
        proxy_info,
        expected_spec_sha256=spec_sha256,
        expected_proxy_url=proxy_url,
    )

    assert initial.proxy_litellm_config_sha256 != changed.proxy_litellm_config_sha256
    assert changed.proxy_litellm_config_sha256 == hashlib.sha256(changed_policy).hexdigest()


def test_validation_metadata_includes_proxy_policy_digest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proxy = ProxyMetadata(
        url="http://cpu-132-021:8103",
        api_key="test-secret-key",
        proxy_info_sha256="a" * 64,
        proxy_litellm_config_sha256="b" * 64,
    )
    monkeypatch.setattr(validate_launch_module, "validate_launch", lambda *args, **kwargs: proxy)

    status = main(
        [
            "--project-dir",
            "/project",
            "--deployment-root",
            "/deployment",
            "--proxy-info",
            "/proxy-info",
            "--eval-config",
            "/eval-config",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == (
        f"{'a' * 64}\t24\t64\t24\t40\t{EXPECTED_CONFIG_SHA256}\t{'b' * 64}\n"
    )
    assert captured.err == ""
    assert "test-secret-key" not in captured.out


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("spec", "deployment_spec_hash_mismatch"),
        ("sticky", "proxy_extras_contract_mismatch"),
        ("endpoint", "endpoint_count_mismatch"),
    ],
)
def test_shared_kimi_deployment_metadata_fails_closed(
    tmp_path: Path,
    mutation: str,
    error: str,
) -> None:
    root, proxy_info, spec_sha256, proxy_url = _deployment(tmp_path)
    if mutation == "spec":
        (root / "spec.yaml").write_text("changed\n")
    elif mutation == "sticky":
        value = json.loads(proxy_info.read_text())
        value["extras"]["sticky"] = False
        proxy_info.write_text(json.dumps(value))
    else:
        next((root / "endpoints").iterdir()).unlink()

    with pytest.raises(SharedKimiValidationError, match=f"^{error}$"):
        validate_deployment(
            root,
            proxy_info,
            expected_spec_sha256=spec_sha256,
            expected_proxy_url=proxy_url,
        )


def test_shared_kimi_runtime_rejects_degraded_route_count() -> None:
    proxy = ProxyMetadata(
        url="http://proxy.example:8103",
        api_key="test-secret-key",
        proxy_info_sha256="a" * 64,
        proxy_litellm_config_sha256="b" * 64,
    )

    with pytest.raises(SharedKimiValidationError, match="^route_health_mismatch$"):
        validate_runtime_metadata(proxy, transport=FakeMetadataTransport(healthy=23, unhealthy=1))


def test_shared_kimi_runtime_errors_do_not_expose_credentials() -> None:
    class FailedTransport:
        def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse:
            raise RuntimeError(headers["Authorization"])

    proxy = ProxyMetadata(
        url="http://proxy.example:8103",
        api_key="test-secret-key",
        proxy_info_sha256="a" * 64,
        proxy_litellm_config_sha256="b" * 64,
    )

    with pytest.raises(SharedKimiValidationError, match="^models_endpoint_invalid$") as captured:
        validate_runtime_metadata(proxy, transport=FailedTransport())
    assert "test-secret-key" not in str(captured.value)


def test_production_eval_config_matches_shared24_contract() -> None:
    project = Path(__file__).parents[4]

    validate_eval_config(project, project / EXPECTED_CONFIG_FILE)
    validate_eval_config(project, project / TB4_CONFIG_FILE, "tb4")
    assert hashlib.sha256((project / EXPECTED_CONFIG_FILE).read_bytes()).hexdigest() == EXPECTED_CONFIG_SHA256
    assert hashlib.sha256((project / TB4_CONFIG_FILE).read_bytes()).hexdigest() == TB4_CONFIG_SHA256
    expected_submodules = {
        "deps/verifiers": EXPECTED_VERIFIERS_REVISION,
        "deps/renderers": EXPECTED_RENDERERS_REVISION,
        "deps/pydantic-config": EXPECTED_PYDANTIC_CONFIG_REVISION,
    }
    for path, expected_revision in expected_submodules.items():
        actual_revision = subprocess.run(
            ["git", "rev-parse", f"HEAD:{path}"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert actual_revision == expected_revision
    tree_identity = _dataset_tree_identity(Path(PROFILES["tb4"].dataset_dir))
    assert tree_identity == (
        TB4_DATASET_TREE_SHA256,
        TB4_DATASET_FILE_COUNT,
        TB4_DATASET_DIRECTORY_COUNT,
    )


def test_dataset_tree_identity_includes_permission_mode_bits(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir(mode=0o755)
    payload = dataset / "payload"
    payload.write_bytes(b"same content\n")
    payload.chmod(0o644)
    initial = _dataset_tree_identity(dataset)

    payload.chmod(0o755)
    changed = _dataset_tree_identity(dataset)

    assert initial[1:] == changed[1:] == (1, 0)
    assert initial[0] != changed[0]


def test_clean_git_worktree_rejects_untracked_files(tmp_path: Path) -> None:
    checkout = tmp_path / "dataset"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    (checkout / "tracked").write_text("pinned\n")
    subprocess.run(["git", "add", "tracked"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"],
        cwd=checkout,
        check=True,
    )

    _require_clean_git_worktree(checkout, git_code="git_invalid", dirty_code="dataset_worktree_dirty")
    (checkout / "untracked").write_text("drift\n")

    with pytest.raises(SharedKimiValidationError, match="^dataset_worktree_dirty$"):
        _require_clean_git_worktree(checkout, git_code="git_invalid", dirty_code="dataset_worktree_dirty")


def test_resume_location_is_pinned_to_server_profile_lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_root = tmp_path / "evals"
    output_root.mkdir()
    profile = PROFILES["mobius"]
    valid = output_root / f"{profile.default_output_prefix}12345"
    valid.mkdir()
    monkeypatch.setattr(validate_launch_module, "EVAL_OUTPUT_ROOT", output_root)

    assert validate_resume_location(valid, profile) == valid

    outside = tmp_path / valid.name
    outside.mkdir()
    with pytest.raises(SharedKimiValidationError, match="^resume_directory_outside_lane$"):
        validate_resume_location(outside, profile)

    wrong_profile = output_root / f"{PROFILES['tb4'].default_output_prefix}12345"
    wrong_profile.mkdir()
    with pytest.raises(SharedKimiValidationError, match="^resume_directory_name_mismatch$"):
        validate_resume_location(wrong_profile, profile)


@pytest.mark.parametrize("profile_name", ["mobius", "tb4"])
def test_resume_contract_accepts_exact_saved_state(tmp_path: Path, profile_name: str) -> None:
    project, resume, proxy = _resume_fixture(tmp_path, profile_name=profile_name)

    assert validate_resume(project, resume, profile_name, proxy) == resume


def test_resume_contract_binds_proxy_policy_digest_in_every_resume_block(tmp_path: Path) -> None:
    project, resume, proxy = _resume_fixture(tmp_path)
    profile = PROFILES["mobius"]
    project_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    resume_block = {
        "resume_slurm_job_id": "67890",
        "resume_prime_rl": project_revision,
        "resume_verifiers": EXPECTED_VERIFIERS_REVISION,
        "resume_renderers": EXPECTED_RENDERERS_REVISION,
        "resume_pydantic_config": EXPECTED_PYDANTIC_CONFIG_REVISION,
        "resume_eval_config_sha256": profile.config_sha256,
        "resume_inference_base_url": "http://cpu-132-021:8103/v1",
        "resume_inference_deployment_id": "",
        "resume_inference_proxy_info_sha256": proxy.proxy_info_sha256,
        "resume_inference_proxy_litellm_config_sha256": proxy.proxy_litellm_config_sha256,
        "resume_dataset_tree_sha256": "",
        "resume_approval_task_file_sha256": profile.task_sha256,
        "resume_approval_task_count": str(profile.task_count),
    }
    provenance = resume / "provenance.txt"
    with provenance.open("a") as handle:
        handle.write("".join(f"{key}={value}\n" for key, value in resume_block.items()))

    assert validate_resume(project, resume, "mobius", proxy) == resume

    provenance.write_text(
        provenance.read_text().replace(
            f"resume_inference_proxy_litellm_config_sha256={proxy.proxy_litellm_config_sha256}",
            f"resume_inference_proxy_litellm_config_sha256={'c' * 64}",
        )
    )
    with pytest.raises(
        SharedKimiValidationError,
        match="^resume_provenance_resume_inference_proxy_litellm_config_sha256_mismatch$",
    ):
        validate_resume(project, resume, "mobius", proxy)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("num_rollouts",), True),
        (("taskset", "use_declared_images"), 1),
        (("sampling", "temperature"), True),
    ],
)
def test_resolved_config_comparison_is_type_exact(
    tmp_path: Path,
    path: tuple[str, ...],
    replacement: object,
) -> None:
    resume = (tmp_path / "resume").resolve()
    resume.mkdir()
    profile = PROFILES["mobius"]
    config = _expected_resolved_config(profile, resume)
    target = config
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(SharedKimiValidationError, match="^resume_config_contract_mismatch$"):
        _validate_common_eval_contract(config, profile, resolved=True, resume_dir=resume)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("saved_config", "resume_config_contract_mismatch"),
        ("source_config", "resume_source_config_hash_mismatch"),
        ("task_snapshot", "resume_task_snapshot_hash_mismatch"),
        ("image_snapshot", "resume_image_snapshot_hash_mismatch"),
        ("manifest", "resume_task_file_record_hash_mismatch"),
        ("manifest_source", "resume_task_file_source_path_mismatch"),
        (
            "provenance",
            "resume_provenance_inference_proxy_info_sha256_mismatch",
        ),
        (
            "proxy_policy_provenance",
            "resume_provenance_inference_proxy_litellm_config_sha256_mismatch",
        ),
    ],
)
def test_resume_contract_rejects_drift(tmp_path: Path, mutation: str, error: str) -> None:
    project, resume, proxy = _resume_fixture(tmp_path)
    if mutation == "saved_config":
        with (resume / "config.toml").open("a") as handle:
            handle.write("unexpected = true\n")
    elif mutation == "source_config":
        with (resume / "inputs" / "source_config.toml").open("ab") as handle:
            handle.write(b"\n# changed\n")
    elif mutation == "task_snapshot":
        with (resume / "inputs" / "task_file.txt").open("ab") as handle:
            handle.write(b"\n")
    elif mutation == "image_snapshot":
        with (resume / "inputs" / "image_manifest.json").open("ab") as handle:
            handle.write(b"\n")
    elif mutation in {"manifest", "manifest_source"}:
        manifest_path = resume / "inputs" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if mutation == "manifest":
            manifest["task_file"]["sha256"] = "b" * 64
        else:
            manifest["task_file"]["source"] = manifest["config"]["source"]
        manifest_path.write_text(json.dumps(manifest))
    elif mutation == "provenance":
        provenance = resume / "provenance.txt"
        provenance.write_text(
            provenance.read_text().replace(
                f"inference_proxy_info_sha256={proxy.proxy_info_sha256}",
                f"inference_proxy_info_sha256={'b' * 64}",
            )
        )
    else:
        provenance = resume / "provenance.txt"
        provenance.write_text(
            provenance.read_text().replace(
                f"inference_proxy_litellm_config_sha256={proxy.proxy_litellm_config_sha256}",
                f"inference_proxy_litellm_config_sha256={'c' * 64}",
            )
        )

    with pytest.raises(SharedKimiValidationError, match=f"^{error}$"):
        validate_resume(project, resume, "mobius", proxy)


def test_shared_launcher_rejects_ambient_generic_resume(tmp_path: Path) -> None:
    common = SERVER_DIR / "launch_common.sh"
    env = {"PATH": os.environ["PATH"], "RESUME_DIR": str(tmp_path / "run")}

    result = subprocess.run(
        ["bash", str(common), "mobius"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == "RESUME_DIR is forbidden for the pinned shared Kimi launcher\n"


def test_shared_launcher_rejects_resume_with_output_override(tmp_path: Path) -> None:
    common = SERVER_DIR / "launch_common.sh"
    env = {
        "PATH": os.environ["PATH"],
        "KIMI_SHARED_RESUME_DIR": str(tmp_path / "run"),
        "OUTPUT_DIR": str(tmp_path / "output"),
    }

    result = subprocess.run(
        ["bash", str(common), "mobius"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == "OUTPUT_DIR is forbidden for the pinned shared Kimi launcher\n"


def test_shared_launcher_rejects_out_of_lane_resume(tmp_path: Path) -> None:
    common = SERVER_DIR / "launch_common.sh"
    resume = tmp_path / "mobius_kimi_k3_shared24_cpu-132-021_8103_12345"
    resume.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "PROJECT_DIR": str(Path(__file__).resolve().parents[4]),
        "SLURM_JOB_ID": "67890",
        "KIMI_SHARED_RESUME_DIR": str(resume),
    }

    result = subprocess.run(
        ["bash", str(common), "mobius"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == "KIMI_SHARED_RESUME_DIR does not belong to this server/profile lane\n"
