from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tarfile
import tempfile
import types
from pathlib import Path

import pytest

BUNDLE = Path(__file__).resolve().parent
CONTROLLER = BUNDLE / "controller.py"


def load_controller() -> types.ModuleType:
    raw = CONTROLLER.read_bytes()
    name = "k3_redeploy_test_" + hashlib.sha256(raw).hexdigest()
    module = types.ModuleType(name)
    module.__file__ = "sealed-test:controller"
    sys.modules[name] = module
    exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
    return module


M = load_controller()
PRODUCTION_BUNDLE = M.BUNDLE
for attribute, filename in (
    ("BUNDLE", "."),
    ("LAUNCHER", "launch.sh"),
    ("CONTROLLER", "controller.py"),
    ("PLAN", "pending.json"),
    ("README", "README.md"),
    ("TESTS", "test_controller.py"),
    ("BUILDER", "build_runtime_zip.py"),
    ("RUNTIME_ZIP", "runtime.zip"),
    ("PYTHON_RUNTIME_TAR", "python-runtime.tar"),
):
    setattr(M, attribute, BUNDLE if filename == "." else BUNDLE / filename)


def result(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    return M.Result(returncode, stdout, stderr)


def run_frozen(code: str) -> subprocess.CompletedProcess[bytes]:
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(
            [
                "/usr/bin/tar",
                "-xf",
                str(M.PYTHON_RUNTIME_TAR),
                "-C",
                directory,
                "--no-same-owner",
            ],
            check=True,
            capture_output=True,
        )
        runtime = Path(directory) / "runtime"
        env = {
            **M.SAFE_ENV,
            "K3_V12B_PYTHON_RUNTIME_ROOT": str(runtime),
            "K3_V12B_RUNTIME_TAR_SHA256": M.PYTHON_RUNTIME_TAR_SHA256,
        }
        return subprocess.run(
            [str(runtime / "bin/python3.12"), "-I", "-S", "-B", "-c", code],
            env=env,
            capture_output=True,
            check=False,
            timeout=60,
        )


def test_candidate_is_inert_and_fresh() -> None:
    assert M.pending_contract()["launch_eligible"] is False
    assert M.pending_contract()["state"] == "pending_independent_approval"
    assert not M.APPROVAL.exists()
    assert not M.RUN_ROOT.exists()
    assert not M.ROUTE_ROOT.exists()
    assert not M.OUTPUT_ROOT.exists()
    assert not M.GLOBAL_LOCK.exists()
    assert not M.DEPLOYMENT_ROOT.exists()
    assert not any(path.name.startswith(M.DEPLOYMENT_ID + "-") for path in M.REMOVED_ROOT.iterdir())


def test_error_code_sanitizer_is_allowlist_only() -> None:
    assert M.sanitized_error_code(M.DeploymentError("publish_verify")) == "publish_verify"
    assert M.sanitized_error_code(M.LaunchCancelled()) == "signal"
    for error in (
        M.DeploymentError("raw detail"),
        M.DeploymentError("path/escape"),
        M.DeploymentError("x" * 65),
        RuntimeError("sensitive raw exception text"),
    ):
        assert M.sanitized_error_code(error) == "internal_error"


def test_exact_plan_contract() -> None:
    plan = M.batch_plan()
    assert M.pending_contract()["lifecycle"]["coordinator_held_incomplete_nodes_retry_only"] is True
    assert PRODUCTION_BUNDLE == Path(
        "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/"
        "k3_tb4_eval_deploy_20260920t034800z_v12b"
    )
    assert plan["deployment_id"] == "tianhaowu-k3-kda-tb4-eval-20260920t034800z"
    assert "tianhaowu-k3-kda-tb4-eval-20260920t020900z" in plan["excluded_stale_deployment_ids"]
    assert "tianhaowu-k3-kda-tb4-eval-20260920t030300z" in plan["excluded_stale_deployment_ids"]
    assert plan["excluded_stale_deployment_ids"] == sorted(M.STALE_DEPLOYMENT_IDS)
    assert plan["source_revision"] == "0322cd43963cbad632128b8e00946a55f16a8085"
    assert plan["source_tree"] == "eac4040827d2ef1a82b067220616cfe8d3459a32"
    assert plan["model"] == "Kimi-K3"
    assert plan["endpoints"] == 2
    assert plan["gpus_per_endpoint"] == 16
    assert plan["worker_qos"] == "g3_lowest"
    assert plan["worker_qos_priority"] == 1
    assert plan["worker_qos_outbound_preempt_targets"] == ["normal"]
    assert plan["worker_time_min"] == "3-00:00:00"
    assert plan["worker_qos_preemptible"] is True
    assert plan["worker_qos_preemptors"] == list(M.EXPECTED_WORKER_QOS_PREEMPTORS)
    assert plan["worker_exclude_nodes"] == list(M.WORKER_EXCLUDE_NODES)
    assert plan["proxy_request_timeout"] == 43_200
    assert plan["proxy_num_retries"] == 0
    assert plan["sticky"] is True
    assert plan["sticky_ttl"] == 14_400
    assert json.loads(plan["compilation_config"]) == {"cudagraph_mode": "PIECEWISE"}
    assert plan["coordinator_cold_standby"] == "exactly_one_afternotok"
    assert plan["serving_runtime_manifests"] == M.SERVING_RUNTIME_MANIFESTS
    assert plan["resume"] is False


def test_exact_deploy_argv() -> None:
    args = list(M.DEPLOY_ARGS)
    assert args.count("--endpoints") == 1 and args[args.index("--endpoints") + 1] == "2"
    assert args.count("--gpus-per-endpoint") == 1 and args[args.index("--gpus-per-endpoint") + 1] == "16"
    assert args.count("--qos") == 1 and args[args.index("--qos") + 1] == "g3_lowest"
    assert args.count("--worker-exclude-node") == 4
    assert [args[index + 1] for index, value in enumerate(args) if value == "--worker-exclude-node"] == list(
        M.WORKER_EXCLUDE_NODES
    )
    assert args.count("--time-min") == 1 and args[args.index("--time-min") + 1] == "3-00:00:00"
    assert args.count("--sticky") == 1
    assert args.count("--sticky-ttl") == 1 and args[args.index("--sticky-ttl") + 1] == "14400"
    assert args.count("--set") == 2
    assert "proxy.config.request_timeout=43200" in args
    assert "proxy.config.num_retries=0" in args
    assert "--lifetime" in args and args[args.index("--lifetime") + 1] == "7d"
    assert "--no-timeout" not in args and "--no-watch" not in args
    assert M.IMAGE in args and "@sha256:" in M.IMAGE


def test_pending_bytes_are_canonical_and_exact() -> None:
    raw = M.PLAN.read_bytes()
    assert raw == M.canonical_bytes(M.pending_contract())


def test_source_and_runtime_manifests_recompute() -> None:
    M.validate_source()
    assert M.validate_runtime_zip() == M.RUNTIME_ZIP.read_bytes()
    code = "\n".join(
        (
            "import sys,types",
            "from pathlib import Path",
            f"p={str(CONTROLLER)!r}",
            "raw=open(p,'rb').read()",
            "m=types.ModuleType('frozen_runtime_validation')",
            "m.__file__='sealed-test'",
            "sys.modules[m.__name__]=m",
            "exec(compile(raw,'sealed-test','exec'),m.__dict__)",
            f"m.PYTHON_RUNTIME_TAR=Path({str(M.PYTHON_RUNTIME_TAR)!r})",
            "m.validate_root_runtime()",
        )
    )
    completed = run_frozen(code)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")


def test_source_manifest_rejects_directory_symlink() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "root"
        outside = Path(directory) / "outside"
        root.mkdir()
        outside.mkdir()
        (root / "escape").symlink_to(outside, target_is_directory=True)
        with pytest.raises(M.DeploymentError, match="manifest_entry"):
            M.content_tree_manifest(root)


def test_serving_runtime_manifests_recompute() -> None:
    assert M.validate_serving_runtime() == M.SERVING_RUNTIME_MANIFESTS


def test_external_runtime_manifest_rejects_escape_symlink() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "root"
        outside = Path(directory) / "outside"
        root.mkdir()
        outside.mkdir()
        (root / "escape").symlink_to(outside, target_is_directory=True)
        with pytest.raises(M.DeploymentError, match="external_runtime_symlink"):
            M.external_tree_manifest(root)


def test_external_runtime_manifest_detects_file_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "root"
        root.mkdir()
        target = root / "runtime.py"
        target.write_bytes(b"runtime")
        real_read = M.os.read
        changed = False

        def racing_read(descriptor: int, size: int) -> bytes:
            nonlocal changed
            block = real_read(descriptor, size)
            if block and not changed:
                changed = True
                target.chmod(0o600)
            return block

        monkeypatch.setattr(M.os, "read", racing_read)
        with pytest.raises(M.DeploymentError, match="external_runtime_race"):
            M.external_tree_manifest(root)


def test_model_provenance_recomputes_without_reading_weights() -> None:
    observed = M.model_provenance()
    assert observed["revision"] == M.MODEL_REVISION
    assert observed["shards"] == 96
    assert observed["manifest_sha256"] == M.MODEL_PROVENANCE_SHA256
    assert observed["weight_binding"] == "immutable-owner-hf-revision-etag-size"


def test_runtime_zip_is_pure_and_closed() -> None:
    import zipfile

    with zipfile.ZipFile(M.RUNTIME_ZIP) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert archive.testzip() is None
        assert all(not name.endswith((".so", ".pyc", ".pyo", ".pth")) for name in names)
        assert "serve_api_v2/cli/deploy.py" in names
        assert "yaml/__init__.py" in names


def test_sealed_runtime_reproduces_explain_and_origins() -> None:
    code = "\n".join(
        (
            "import sys,types",
            f"p={str(CONTROLLER)!r}",
            "raw=open(p,'rb').read()",
            "m=types.ModuleType('sealed_controller_test')",
            "m.__file__='sealed-test'",
            "sys.modules[m.__name__]=m",
            "exec(compile(raw,'sealed-test','exec'),m.__dict__)",
            f"m.RUNTIME_ZIP=__import__('pathlib').Path({str(M.RUNTIME_ZIP)!r})",
            "api=m.load_serve_api(m.validate_runtime_zip())",
            "assert m.run_explain(api)==m.EXPLAIN_NORMALIZED_SHA256",
            "m.validate_import_origins(api)",
            "assert api.deploy.__spec__.origin.startswith(api.runtime_path+'/')",
            "assert api.yaml.__spec__.origin.startswith(api.runtime_path+'/')",
            "m.close_serve_api(api)",
        )
    )
    completed = run_frozen(code)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")


def test_dry_deploy_reproduces_initial_and_final_specs_without_sbatch() -> None:
    code = "\n".join(
        (
            "import contextlib,io,json,os,sys,tempfile,types",
            "from pathlib import Path",
            f"raw=Path({str(CONTROLLER)!r}).read_bytes()",
            "m=types.ModuleType('dry_deploy_controller')",
            "m.__file__='sealed-test'",
            "sys.modules[m.__name__]=m",
            "exec(compile(raw,'sealed-test','exec'),m.__dict__)",
            f"m.RUNTIME_ZIP=Path({str(M.RUNTIME_ZIP)!r})",
            "with tempfile.TemporaryDirectory() as root:",
            " os.environ['V2_DEPLOYMENTS_ROOT']=root",
            " api=m.load_serve_api(m.validate_runtime_zip())",
            " captured={}",
            " def held(s,dep_dir,deployment_id):",
            "  argv,exports=api.deploy.coordinator_sbatch_argv(s=s,dep_dir=dep_dir,deployment_id=deployment_id)",
            "  captured['exports']=exports",
            "  return '1'",
            " api.deploy._sbatch_coordinator=held",
            " old=Path.cwd();os.chdir(m.SERVE_ROOT)",
            " try:",
            "  with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()): rc=api.deploy.main([*m.DEPLOY_ARGS,'--no-watch'])",
            " finally: os.chdir(old)",
            " assert rc==0",
            " dep=Path(root)/m.DEPLOYMENT_ID;sp=dep/'spec.yaml'",
            " initial,_=m.normalized_spec(sp.read_bytes(),api.yaml)",
            " specmod=__import__('serve_api_v2.spec',fromlist=['x'])",
            " meta,s=specmod.load(sp)",
            " endpoint=specmod.endpoint_sbatch_argv(s,m.DEPLOYMENT_ID,'/worker.sbatch')",
            " proxy=specmod.proxy_sbatch_argv(s,m.DEPLOYMENT_ID,'/proxy.sbatch')",
            " coord,_=api.deploy.coordinator_sbatch_argv(s=s,dep_dir=dep,deployment_id=m.DEPLOYMENT_ID)",
            " expected_exclude='--exclude='+','.join(m.WORKER_EXCLUDE_NODES)",
            " assert [a for a in endpoint if a.startswith('--exclude=')]==[expected_exclude]",
            " assert not any(a.startswith('--exclude=') for a in proxy)",
            " assert not any(a.startswith('--exclude=') for a in coord)",
            " final=specmod.materialize_checkpoint(s,s.checkpoint_candidates[0])",
            " specmod.dump(meta,final,sp)",
            " final_sha,_=m.normalized_spec(sp.read_bytes(),api.yaml)",
            " expected={'DEPLOYMENT_DIR':str(dep),'DEPLOYMENT_ID':m.DEPLOYMENT_ID,'SERVE_API_V2_SRC_DIR':str(dep/'src/serve_api_v2'),'PIXI_ENVS_DIR':str(m.PIXI_ENVS_ROOT),'PIXI_BIN_DIR':str(m.PIXI_BIN_ROOT),'COORD_PIXI_ENV':m.COORDINATOR_ENV}",
            " assert captured['exports']==expected",
            " assert m.content_tree_manifest(dep/'src/serve_api_v2')==m.SNAPSHOT_MANIFEST",
            " print(json.dumps([initial,final_sha],separators=(',',':')))",
            " m.close_serve_api(api)",
        )
    )
    completed = run_frozen(code)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    assert json.loads(completed.stdout) == [
        M.INITIAL_SPEC_NORMALIZED_SHA256,
        M.FINAL_SPEC_NORMALIZED_SHA256,
    ]


def test_runtime_builder_is_reproducible(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location("runtime_builder_test", M.BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "runtime.zip"
        monkeypatch.setattr(module, "OUTPUT", target)
        monkeypatch.setattr(sys, "argv", [str(M.BUILDER)])
        assert module.main() == 0
        assert hashlib.sha256(target.read_bytes()).hexdigest() == M.RUNTIME_ZIP_SHA256


def test_normalize_explain_rejects_bad_encoding() -> None:
    with pytest.raises(M.DeploymentError, match="explain_encoding"):
        M.normalize_explain(b"\xff")


def test_parse_scontrol_preserves_space_values() -> None:
    parsed = M.parse_scontrol(
        b"JobId=123 JobName=name UserId=tianhaowu(656177) NumTasks=4 CPUs/Task=96 Command=/a/b WorkDir=/a c Account=everyone"
    )
    assert parsed["JobId"] == "123"
    assert parsed["CPUs/Task"] == "96"
    assert parsed["WorkDir"] == "/a c"
    assert parsed["Account"] == "everyone"


def test_parse_scontrol_rejects_multiline() -> None:
    with pytest.raises(M.SchedulerUnavailable, match="scontrol_shape"):
        M.parse_scontrol(b"JobId=1\nJobId=2")


def test_worker_backfill_time_limit_is_bounded() -> None:
    assert M.slurm_duration_seconds("12:00:00") == 43_200
    assert M.slurm_duration_seconds("7-00:00:00") == 604_800
    with pytest.raises(M.DeploymentError, match="slurm_duration"):
        M.slurm_duration_seconds("7-25:00:00")


def test_name_query_rejects_malformed_accounting_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = iter((result(stdout=b""), result(stdout=b"123\n")))
    monkeypatch.setattr(M, "run_command", lambda *_args, **_kwargs: next(outputs))
    with pytest.raises(M.DeploymentError, match="scheduler_query_shape"):
        M.name_job_ids()


def expected_submit_argv() -> list[str]:
    return [
        "sbatch",
        f"--job-name={M.JOB_NAME}",
        "--no-requeue",
        "--signal=B:USR1@600",
        "--partition=cpu_x86",
        "--account=everyone",
        "--qos=cpu_x86_lowest",
        f"--time={M.JOB_TIME_LIMIT}",
        "--cpus-per-task=4",
        "--gpus-per-task=0",
        "--mem=16G",
        f"--output={M.DEPLOYMENT_ROOT}/slurm_logs/%j.coord.log",
        f"--error={M.DEPLOYMENT_ROOT}/slurm_logs/%j.coord.log",
        "--export=ALL",
        str(M.DEPLOYMENT_ROOT / "src/serve_api_v2/coordinator/coordinator.sbatch"),
    ]


def expected_exports() -> dict[str, str]:
    return {
        "DEPLOYMENT_DIR": str(M.DEPLOYMENT_ROOT),
        "DEPLOYMENT_ID": M.DEPLOYMENT_ID,
        "SERVE_API_V2_SRC_DIR": str(M.DEPLOYMENT_ROOT / "src/serve_api_v2"),
        "PIXI_ENVS_DIR": str(M.PIXI_ENVS_ROOT),
        "PIXI_BIN_DIR": str(M.PIXI_BIN_ROOT),
        "COORD_PIXI_ENV": M.COORDINATOR_ENV,
    }


def expected_bundle_hashes() -> dict[str, str]:
    return {
        "launcher": "1" * 64,
        "controller": "2" * 64,
        "plan": "3" * 64,
        "readme": "4" * 64,
        "tests": "5" * 64,
        "builder": "6" * 64,
        "runtime_zip": "7" * 64,
        "python_runtime": "8" * 64,
    }


def expected_approval(hashes: dict[str, str]) -> tuple[str, dict[str, object]]:
    payload = M.approval_contract(hashes)
    return hashlib.sha256(M.canonical_bytes(payload)).hexdigest(), payload


def expected_coordinator_record(job_id: str = "12345", token: str = "token") -> dict[str, str]:
    coordinator_log = str(M.DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.coord.log")
    return {
        "JobId": job_id,
        "JobName": M.JOB_NAME,
        "UserId": M.OWNER_RECORD,
        "Comment": token,
        "Command": str(M.DEPLOYMENT_ROOT / "src/serve_api_v2/coordinator/coordinator.sbatch"),
        "WorkDir": str(M.SERVE_ROOT),
        "Account": "everyone",
        "QOS": "cpu_x86_lowest",
        "Partition": "cpu_x86",
        "NumNodes": "1",
        "NumCPUs": "4",
        "TimeLimit": M.JOB_TIME_LIMIT,
        "StdOut": coordinator_log,
        "StdErr": coordinator_log,
        "Requeue": "0",
        "Restarts": "0",
        "JobState": "PENDING",
        "Reason": "JobHeldUser",
        "Priority": "0",
        "EligibleTime": "Unknown",
    }


def neutralize_submit_prechecks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(M, "validate_source", lambda: None)
    monkeypatch.setattr(M, "model_provenance", lambda: {})
    monkeypatch.setattr(M, "validate_spec", lambda *_args, **_kwargs: ("a" * 64, "b" * 64))
    monkeypatch.setattr(M, "content_tree_manifest", lambda _path: M.SNAPSHOT_MANIFEST)
    monkeypatch.setattr(M, "prove_name_absent", lambda *args, **kwargs: None)
    monkeypatch.setattr(M, "CURRENT_API", object())
    M.SUBMITTED_JOB_ID = None
    M.SUBMITTED_DIRECT = False
    M.SUBMIT_ERROR_CODE = None


def test_submit_is_held_parsable_and_identity_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    seen = {}

    def bounded(argv, env):
        seen["argv"] = list(argv)
        seen["env"] = dict(env)
        return "completed", 0, b"12345;fair-cw-use2-3\n", True

    monkeypatch.setattr(M, "bounded_submit", bounded)
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"12345"})
    identities = []
    monkeypatch.setattr(
        M,
        "coordinator_identity",
        lambda job, token, held: identities.append((job, token, held))
        or expected_coordinator_record(job, token),
    )
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda _delay: False)
    assert M.submit_held(expected_submit_argv(), expected_exports(), "token") == "12345"
    assert seen["argv"][:4] == [
        "/usr/bin/sbatch",
        "--parsable",
        "--hold",
        "--comment=token",
    ]
    assert identities == [("12345", "token", True)] * 2
    assert M.SUBMITTED_DIRECT is True


def test_submit_malformed_zero_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    neutralize_submit_prechecks(monkeypatch)
    monkeypatch.setattr(M, "bounded_submit", lambda *_args, **_kwargs: ("completed", 0, b"bad\n", True))
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda _delay: False)
    with pytest.raises(M.DeploymentError, match="submission_missing"):
        M.submit_held(expected_submit_argv(), expected_exports(), "token")


def test_submit_rejects_extra_argv_or_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    argv = expected_submit_argv()
    argv.insert(-1, "--dependency=afterany:999")
    with pytest.raises(M.DeploymentError, match="coordinator_argv"):
        M.submit_held(argv, expected_exports(), "token")
    exports = expected_exports()
    exports["INJECTED"] = "1"
    with pytest.raises(M.DeploymentError, match="coordinator_environment"):
        M.submit_held(expected_submit_argv(), exports, "token")


def test_submit_conflict_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    neutralize_submit_prechecks(monkeypatch)
    monkeypatch.setattr(M, "bounded_submit", lambda *_args, **_kwargs: ("timeout", 127, b"", True))
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"123", "124"})
    with pytest.raises(M.DeploymentError, match="submission_conflict"):
        M.submit_held(expected_submit_argv(), expected_exports(), "token")


def test_submit_reconciled_ambiguity_never_returns_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    monkeypatch.setattr(M, "bounded_submit", lambda *_args, **_kwargs: ("timeout", 127, b"", True))
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"123"})
    monkeypatch.setattr(M, "coordinator_identity", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda _delay: False)
    with pytest.raises(M.DeploymentError, match="submission_ambiguous_reconciled"):
        M.submit_held(expected_submit_argv(), expected_exports(), "token")
    assert M.SUBMITTED_JOB_ID == "123"


def test_submit_records_direct_id_and_bounds_transient_identity_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    submissions: list[int] = []
    releases: list[int] = []

    def bounded(*_args, **_kwargs):
        submissions.append(1)
        return "completed", 0, b"123;fair-cw-use2-3\n", True

    monkeypatch.setattr(M, "bounded_submit", bounded)
    monkeypatch.setattr(M, "release_job", lambda *_args, **_kwargs: releases.append(1))
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"123"})
    attempts: list[int] = []

    def unavailable(*_args, **_kwargs):
        attempts.append(1)
        raise M.SchedulerUnavailable("coordinator_command_failed")

    monkeypatch.setattr(M, "coordinator_identity", unavailable)
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda _delay: False)
    with pytest.raises(M.DeploymentError, match="coordinator_command_failed"):
        M.submit_held(expected_submit_argv(), expected_exports(), "token")
    assert M.SUBMITTED_JOB_ID == "123"
    assert M.SUBMITTED_DIRECT is True
    assert submissions == [1]
    assert releases == []
    assert len(attempts) == M.COORDINATOR_IDENTITY_ROUNDS


def test_submit_retries_transient_held_reason_then_requires_two_stable_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    submissions: list[int] = []
    releases: list[int] = []

    def bounded(*_args, **_kwargs):
        submissions.append(1)
        return "completed", 0, b"12345;fair-cw-use2-3\n", True

    monkeypatch.setattr(M, "bounded_submit", bounded)
    monkeypatch.setattr(M, "release_job", lambda *_args, **_kwargs: releases.append(1))
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"12345"})
    attempts: list[int] = []
    waits: list[float] = []

    def identity(job: str, token: str, *, held: bool) -> dict[str, str]:
        attempts.append(1)
        if len(attempts) == 1:
            raise M.SchedulerUnavailable("coordinator_command_failed")
        if len(attempts) == 2:
            raise M.CoordinatorIdentityTransient("coordinator_held_reason")
        return expected_coordinator_record(job, token)

    monkeypatch.setattr(M, "coordinator_identity", identity)
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda delay: waits.append(delay) or False)
    assert M.submit_held(expected_submit_argv(), expected_exports(), "token") == "12345"
    assert submissions == [1]
    assert releases == []
    assert len(attempts) == 4
    assert waits == [M.COORDINATOR_IDENTITY_INTERVAL] * 3


def test_submit_retries_incomplete_held_nodes_then_requires_two_exact_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    monkeypatch.setattr(
        M,
        "bounded_submit",
        lambda *_args, **_kwargs: ("completed", 0, b"12345;fair-cw-use2-3\n", True),
    )
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"12345"})
    nodes = iter(("0-1", "0", "1", "1"))
    reads: list[str] = []
    waits: list[float] = []

    def show(_job: str) -> dict[str, str]:
        record = expected_coordinator_record()
        record["NumNodes"] = next(nodes)
        reads.append(record["NumNodes"])
        return record

    monkeypatch.setattr(M, "show_job", show)
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda delay: waits.append(delay) or False)
    assert M.submit_held(expected_submit_argv(), expected_exports(), "token") == "12345"
    assert reads == ["0-1", "0", "1", "1"]
    assert waits == [M.COORDINATOR_IDENTITY_INTERVAL] * 3


@pytest.mark.parametrize("nodes", (None, "", "0", "0-1"))
def test_only_incomplete_held_node_projections_are_transient(
    monkeypatch: pytest.MonkeyPatch, nodes: str | None
) -> None:
    record = expected_coordinator_record()
    if nodes is None:
        del record["NumNodes"]
    else:
        record["NumNodes"] = nodes
    monkeypatch.setattr(M, "show_job", lambda _job: record)
    with pytest.raises(M.CoordinatorIdentityTransient, match="^coordinator_nodes$"):
        M.coordinator_identity("12345", "token", held=True)


@pytest.mark.parametrize("nodes", ("2", "1-2", "Unknown", "(null)"))
def test_definite_held_node_mismatch_fails_without_retry(
    monkeypatch: pytest.MonkeyPatch, nodes: str
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    record = expected_coordinator_record()
    record["NumNodes"] = nodes
    reads: list[int] = []
    waits: list[float] = []

    def show(_job: str) -> dict[str, str]:
        reads.append(1)
        return record

    monkeypatch.setattr(
        M,
        "bounded_submit",
        lambda *_args, **_kwargs: ("completed", 0, b"12345;fair-cw-use2-3\n", True),
    )
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"12345"})
    monkeypatch.setattr(M, "show_job", show)
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda delay: waits.append(delay) or False)
    with pytest.raises(M.DeploymentError, match="^coordinator_nodes$") as captured:
        M.submit_held(expected_submit_argv(), expected_exports(), "token")
    assert type(captured.value) is M.DeploymentError
    assert reads == [1]
    assert waits == []


@pytest.mark.parametrize(
    "field,value,error",
    (
        ("QOS", "wrong", "coordinator_qos"),
        ("JobState", "RUNNING", "coordinator_held_state"),
        ("Priority", "1", "coordinator_held_priority"),
        ("EligibleTime", "2026-09-20T03:48:00", "coordinator_held_eligible"),
        ("Reason", "Resources", "coordinator_held_reason"),
    ),
)
def test_incomplete_nodes_never_mask_dangerous_held_drift(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str, error: str
) -> None:
    record = expected_coordinator_record()
    record["NumNodes"] = "0-1"
    record[field] = value
    monkeypatch.setattr(M, "show_job", lambda _job: record)
    with pytest.raises(M.DeploymentError, match=f"^{error}$") as captured:
        M.coordinator_identity("12345", "token", held=True)
    assert type(captured.value) is M.DeploymentError


def test_incomplete_nodes_are_never_tolerated_outside_held_convergence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = expected_coordinator_record()
    record["NumNodes"] = "0"
    monkeypatch.setattr(M, "show_job", lambda _job: record)
    with pytest.raises(M.DeploymentError, match="^coordinator_nodes$") as captured:
        M.coordinator_static_identity("12345", "token")
    assert type(captured.value) is M.DeploymentError


def test_submit_static_identity_drift_fails_immediately_without_resubmit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    submissions: list[int] = []
    identity_attempts: list[int] = []
    waits: list[float] = []

    def bounded(*_args, **_kwargs):
        submissions.append(1)
        return "completed", 0, b"12345;fair-cw-use2-3\n", True

    def mismatch(*_args, **_kwargs):
        identity_attempts.append(1)
        raise M.DeploymentError("coordinator_qos")

    monkeypatch.setattr(M, "bounded_submit", bounded)
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"12345"})
    monkeypatch.setattr(M, "coordinator_identity", mismatch)
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda delay: waits.append(delay) or False)
    with pytest.raises(M.DeploymentError, match="coordinator_qos"):
        M.submit_held(expected_submit_argv(), expected_exports(), "token")
    assert submissions == [1]
    assert identity_attempts == [1]
    assert waits == []


def test_submit_all_rounds_transient_reason_exhausts_exact_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    submissions: list[int] = []
    releases: list[int] = []
    waits: list[float] = []

    def bounded(*_args, **_kwargs):
        submissions.append(1)
        return "completed", 0, b"12345;fair-cw-use2-3\n", True

    record = expected_coordinator_record()
    record["Reason"] = "None"
    monkeypatch.setattr(M, "bounded_submit", bounded)
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"12345"})
    monkeypatch.setattr(M, "show_job", lambda _job: record)
    monkeypatch.setattr(M, "release_job", lambda *_args, **_kwargs: releases.append(1))
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda delay: waits.append(delay) or False)
    with pytest.raises(M.DeploymentError, match="coordinator_held_reason"):
        M.submit_held(expected_submit_argv(), expected_exports(), "token")
    assert submissions == [1]
    assert releases == []
    assert len(waits) == M.COORDINATOR_IDENTITY_ROUNDS - 1


def test_submit_last_round_single_good_read_is_not_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    submissions: list[int] = []
    releases: list[int] = []

    def bounded(*_args, **_kwargs):
        submissions.append(1)
        return "completed", 0, b"12345;fair-cw-use2-3\n", True

    monkeypatch.setattr(M, "bounded_submit", bounded)
    monkeypatch.setattr(M, "release_job", lambda *_args, **_kwargs: releases.append(1))
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"12345"})
    attempts: list[int] = []

    def identity(job: str, token: str, *, held: bool) -> dict[str, str]:
        attempts.append(1)
        if len(attempts) < M.COORDINATOR_IDENTITY_ROUNDS:
            raise M.CoordinatorIdentityTransient("coordinator_held_reason")
        return expected_coordinator_record(job, token)

    monkeypatch.setattr(M, "coordinator_identity", identity)
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda _delay: False)
    with pytest.raises(M.DeploymentError, match="coordinator_identity_unstable"):
        M.submit_held(expected_submit_argv(), expected_exports(), "token")
    assert submissions == [1]
    assert releases == []
    assert len(attempts) == M.COORDINATOR_IDENTITY_ROUNDS


@pytest.mark.parametrize(
    "field,value,error",
    (
        ("JobState", "RUNNING", "coordinator_held_state"),
        ("Priority", "1", "coordinator_held_priority"),
        ("EligibleTime", "2026-09-20T03:48:00", "coordinator_held_eligible"),
    ),
)
def test_submit_runnable_or_eligible_identity_fails_without_retry(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str, error: str
) -> None:
    neutralize_submit_prechecks(monkeypatch)
    submissions: list[int] = []
    reads: list[int] = []
    waits: list[float] = []
    record = expected_coordinator_record()
    record[field] = value

    def bounded(*_args, **_kwargs):
        submissions.append(1)
        return "completed", 0, b"12345;fair-cw-use2-3\n", True

    def show(_job: str) -> dict[str, str]:
        reads.append(1)
        return record

    monkeypatch.setattr(M, "bounded_submit", bounded)
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"12345"})
    monkeypatch.setattr(M, "show_job", show)
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda delay: waits.append(delay) or False)
    with pytest.raises(M.DeploymentError, match=error):
        M.submit_held(expected_submit_argv(), expected_exports(), "token")
    assert submissions == [1]
    assert reads == [1]
    assert waits == []


@pytest.mark.parametrize(
    "field,value,error",
    (
        ("JobName", "wrong", "coordinator_job_name"),
        ("UserId", "wrong", "coordinator_user"),
        ("Comment", "wrong", "coordinator_comment"),
        ("Command", "/wrong", "coordinator_command"),
        ("WorkDir", "/wrong", "coordinator_workdir"),
        ("Account", "wrong", "coordinator_account"),
        ("QOS", "wrong", "coordinator_qos"),
        ("Partition", "wrong", "coordinator_partition"),
        ("NumNodes", "2", "coordinator_nodes"),
        ("NumCPUs", "8", "coordinator_cpus"),
        ("TimeLimit", "1:00:00", "coordinator_time_limit"),
        ("StdOut", "/wrong", "coordinator_stdout"),
        ("StdErr", "/wrong", "coordinator_stderr"),
        ("Requeue", "1", "coordinator_requeue"),
        ("Restarts", "1", "coordinator_restarts"),
        ("JobState", "RUNNING", "coordinator_held_state"),
        ("Priority", "1", "coordinator_held_priority"),
        ("EligibleTime", "2026-09-20T03:48:00", "coordinator_held_eligible"),
        ("Reason", "None", "coordinator_held_reason"),
    ),
)
def test_coordinator_identity_reports_exact_field(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str, error: str
) -> None:
    record = expected_coordinator_record()
    record[field] = value
    monkeypatch.setattr(M, "show_job", lambda _job: record)
    with pytest.raises(M.DeploymentError, match=error):
        M.coordinator_identity("12345", "token", held=True)


def test_definitive_wrong_held_reason_is_not_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    record = expected_coordinator_record()
    record["Reason"] = "Resources"
    monkeypatch.setattr(M, "show_job", lambda _job: record)
    with pytest.raises(M.DeploymentError, match="coordinator_held_reason") as captured:
        M.coordinator_identity("12345", "token", held=True)
    assert type(captured.value) is M.DeploymentError


def test_coordinator_query_error_is_prefixed_and_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        M,
        "show_job",
        lambda _job: (_ for _ in ()).throw(M.SchedulerUnavailable("command_failed")),
    )
    with pytest.raises(M.SchedulerUnavailable, match="coordinator_command_failed"):
        M.coordinator_identity("12345", "token", held=True)


@pytest.mark.parametrize(
    "raw_code,expected_code",
    (
        ("coordinator_held_reason", "coordinator_held_reason"),
        ("raw / scheduler detail", "internal_error"),
    ),
)
def test_run_deploy_preserves_only_nested_sanitized_submit_error(
    monkeypatch: pytest.MonkeyPatch, raw_code: str, expected_code: str
) -> None:
    class FakeDeploy:
        def __init__(self) -> None:
            self._sbatch_coordinator = lambda *_args, **_kwargs: "unused"

        @staticmethod
        def coordinator_sbatch_argv(*_args, **_kwargs):
            return expected_submit_argv(), expected_exports()

        def main(self, _argv):
            try:
                self._sbatch_coordinator(None, M.DEPLOYMENT_ROOT, M.DEPLOYMENT_ID)
            except RuntimeError:
                return 1
            raise AssertionError("nested submit unexpectedly succeeded")

    monkeypatch.setattr(
        M,
        "submit_held",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(M.DeploymentError(raw_code)),
    )
    api = types.SimpleNamespace(deploy=FakeDeploy())
    M.SUBMIT_ERROR_CODE = "stale_error_must_be_reset"
    with pytest.raises(M.DeploymentError, match=expected_code):
        M.run_deploy(api, "token")
    assert M.SUBMIT_ERROR_CODE == expected_code


def test_wrong_uid_never_scancels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        M,
        "show_job",
        lambda _job: {
            "JobName": M.JOB_NAME,
            "UserId": "other(1)",
            "Comment": "token",
            "Command": str(M.DEPLOYMENT_ROOT / "src/serve_api_v2/coordinator/coordinator.sbatch"),
        },
    )
    calls = []
    monkeypatch.setattr(M, "run_command", lambda *args, **kwargs: calls.append(args) or result())
    assert M.cancel_exact("123", "token", True) is False
    assert calls == []


def test_direct_submit_can_cancel_only_on_scheduler_unavailability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        M,
        "show_job",
        lambda _job: (_ for _ in ()).throw(M.SchedulerUnavailable("unavailable")),
    )
    calls = []
    monkeypatch.setattr(
        M,
        "run_command",
        lambda argv, **_kwargs: calls.append(tuple(argv)) or result(),
    )
    monkeypatch.setattr(M, "prove_terminal", lambda _job: True)
    assert M.cancel_exact("123", "token", direct=True) is True
    assert calls == [("/usr/bin/scancel", "123")]


def test_identity_failure_never_uses_direct_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        M,
        "show_job",
        lambda _job: (_ for _ in ()).throw(M.DeploymentError("identity")),
    )
    calls = []
    monkeypatch.setattr(M, "run_command", lambda *_args, **_kwargs: calls.append(1) or result())
    assert M.cancel_exact("123", "token", direct=True) is False
    assert calls == []


def test_release_waits_until_job_is_not_held(monkeypatch: pytest.MonkeyPatch) -> None:
    records = iter(
        (
            {"JobState": "PENDING", "Reason": "JobHeldUser"},
            {"JobState": "PENDING", "Reason": "Priority"},
        )
    )
    monkeypatch.setattr(M, "coordinator_identity", lambda *_args, **_kwargs: next(records))
    monkeypatch.setattr(M, "run_command", lambda *_args, **_kwargs: result())
    monkeypatch.setattr(M.time, "sleep", lambda _delay: None)
    M.release_job("123", "token")


def standby_record(job_id: str = "124", primary: str = "123") -> dict[str, str]:
    return {
        "JobId": job_id,
        "JobName": M.JOB_NAME,
        "UserId": M.OWNER_RECORD,
        "Command": str(M.DEPLOYMENT_ROOT / "src/serve_api_v2/coordinator/coordinator.sbatch"),
        "WorkDir": str(M.SERVE_ROOT),
        "Account": "everyone",
        "QOS": "cpu_x86_lowest",
        "Partition": "cpu_x86",
        "NumNodes": "1",
        "NumCPUs": "4",
        "TimeLimit": M.JOB_TIME_LIMIT,
        "StdOut": str(M.DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.coord.log"),
        "StdErr": str(M.DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.coord.log"),
        "Requeue": "0",
        "Restarts": "0",
        "JobState": "PENDING",
        "Reason": "Dependency",
        "Dependency": f"afternotok:{primary}(unfulfilled)",
    }


def test_standby_waits_then_binds_exact_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries = iter(({"123"}, {"123", "124"}))
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: next(queries))
    monkeypatch.setattr(M, "show_job", lambda _job: standby_record())
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda _delay: False)
    assert M.standby_identity("123", wait_seconds=30) == "124"


def test_standby_rejects_wrong_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    record = standby_record()
    record["Dependency"] = "afternotok:999(unfulfilled)"
    monkeypatch.setattr(M, "name_job_ids", lambda *_args, **_kwargs: {"123", "124"})
    monkeypatch.setattr(M, "show_job", lambda _job: record)
    with pytest.raises(M.DeploymentError, match="coordinator_standby_identity"):
        M.standby_identity("123", wait_seconds=0)


def test_service_job_identity_is_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = {
        "JobId": "201",
        "JobName": f"{M.DEPLOYMENT_ID}-ep",
        "UserId": M.OWNER_RECORD,
        "JobState": "RUNNING",
        "WorkDir": str(M.SERVE_ROOT),
        "Requeue": "0",
        "Restarts": "0",
        "Account": "ram",
        "QOS": M.WORKER_QOS,
        "Partition": "g3",
        "ExcNodeList": ",".join(M.WORKER_EXCLUDE_NODES),
        "NumNodes": "4",
        "NumCPUs": "384",
        "TimeMin": "3-00:00:00",
        "TimeLimit": M.JOB_TIME_LIMIT,
        "Command": str(M.DEPLOYMENT_ROOT / "src/serve_api_v2/worker/worker.sbatch"),
        "StdOut": str(M.DEPLOYMENT_ROOT / "slurm_logs/201.worker.log"),
        "StdErr": str(M.DEPLOYMENT_ROOT / "slurm_logs/201.worker.log"),
    }
    monkeypatch.setattr(M, "show_job", lambda _job: worker)
    assert M.service_job_identity("201", "worker") == worker
    worker["TimeLimit"] = "12:00:00"
    assert M.service_job_identity("201", "worker") == worker
    worker["TimeLimit"] = "11:59:59"
    with pytest.raises(M.DeploymentError, match="service_job_identity"):
        M.service_job_identity("201", "worker")
    worker["TimeLimit"] = M.JOB_TIME_LIMIT
    worker["QOS"] = "normal"
    with pytest.raises(M.DeploymentError, match="service_job_identity"):
        M.service_job_identity("201", "worker")
    worker["QOS"] = M.WORKER_QOS
    worker["ExcNodeList"] = ",".join(M.WORKER_EXCLUDE_NODES[:-1])
    with pytest.raises(M.DeploymentError, match="service_job_identity"):
        M.service_job_identity("201", "worker")


def test_cleanup_accepts_only_verified_post_release_standby(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = {
        M.JOB_NAME: {"123", "124"},
        f"{M.DEPLOYMENT_ID}-ep": {"201", "202"},
        f"{M.DEPLOYMENT_ID}-proxy": {"203"},
    }
    monkeypatch.setattr(M, "SUBMITTED_JOB_ID", "123")
    monkeypatch.setattr(M, "SUBMITTED_DIRECT", True)
    monkeypatch.setattr(M, "COORDINATOR_RELEASED", True)
    monkeypatch.setattr(M, "name_job_ids", lambda name=M.JOB_NAME: mapping[name])
    monkeypatch.setattr(M, "coordinator_static_identity", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(M, "validate_standby_job", lambda *_args, **_kwargs: {})
    cancelled = []
    monkeypatch.setattr(
        M,
        "cancel_exact",
        lambda job, *_args, **_kwargs: cancelled.append(job) or True,
    )
    monkeypatch.setattr(M, "archive_failed_namespace", lambda: True)
    cleanup = M.cleanup("token", [])
    assert cleanup["all_terminal"] is True
    assert cleanup["namespace_archived"] is True
    assert cancelled == ["123", "124", "201", "202", "203"]


def test_cleanup_refuses_unexpected_coordinator_before_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(M, "SUBMITTED_JOB_ID", "123")
    monkeypatch.setattr(M, "COORDINATOR_RELEASED", False)
    monkeypatch.setattr(
        M,
        "name_job_ids",
        lambda name=M.JOB_NAME: {"123", "124"} if name == M.JOB_NAME else set(),
    )
    calls = []
    monkeypatch.setattr(M, "cancel_exact", lambda *_args, **_kwargs: calls.append(1) or True)
    cleanup = M.cleanup("token", ["123"])
    assert cleanup["identity_conflict"] is True
    assert cleanup["all_terminal"] is False
    assert calls == []


def test_post_release_cleanup_requires_complete_name_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(M, "SUBMITTED_JOB_ID", "123")
    monkeypatch.setattr(M, "SUBMITTED_DIRECT", True)
    monkeypatch.setattr(M, "COORDINATOR_RELEASED", True)

    def names(name=M.JOB_NAME):
        if name == f"{M.DEPLOYMENT_ID}-ep":
            raise M.SchedulerUnavailable("unavailable")
        return {"123"} if name == M.JOB_NAME else set()

    monkeypatch.setattr(M, "name_job_ids", names)
    monkeypatch.setattr(M, "cancel_exact", lambda *_args, **_kwargs: True)
    archived = []
    monkeypatch.setattr(M, "archive_failed_namespace", lambda: archived.append(True) or True)
    cleanup = M.cleanup("token", ["123"])
    assert cleanup["query_unavailable"] is True
    assert cleanup["all_terminal"] is False
    assert cleanup["namespace_archived"] is False
    assert archived == []


@pytest.mark.parametrize(
    ("stop_result", "completed", "category"),
    (
        (0, True, None),
        (1, False, "stop_nonzero"),
        (True, False, "stop_result_invalid"),
        ("raise", False, "RuntimeError"),
    ),
)
def test_exact_deployment_stop_is_namespace_scoped_and_scrubs_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stop_result: object,
    completed: bool,
    category: str | None,
) -> None:
    root = tmp_path / "deployments"
    target = root / M.DEPLOYMENT_ID
    removed = root / ".removed"
    stale = removed / f"{sorted(M.STALE_DEPLOYMENT_IDS)[0]}-archived"
    root.mkdir()
    target.mkdir()
    removed.mkdir()
    stale.mkdir()
    stale_record = stale / "receipt.json"
    stale_record.write_text('{"state":"archived"}\n')
    before = (M.signature(stale.lstat()), M.signature(stale_record.lstat()), stale_record.read_bytes())
    observed = {}
    def original_prune(_root):
        raise AssertionError("prune called")

    class Stop:
        COORD_DRAIN_TIMEOUT_S = 60
        CHILD_DRAIN_TIMEOUT_S = 120
        paths = types.SimpleNamespace(prune_removed_dir=original_prune)

        @staticmethod
        def main(argv):
            observed["argv"] = argv
            observed["environment"] = dict(os.environ)
            observed["prune_was_replaced"] = Stop.paths.prune_removed_dir is not original_prune
            observed["prune_result"] = Stop.paths.prune_removed_dir(root)
            if stop_result == "raise":
                raise RuntimeError("stop failed")
            return stop_result

    monkeypatch.setattr(M, "DEPLOYMENTS_ROOT", root)
    monkeypatch.setattr(M, "DEPLOYMENT_ROOT", target)
    monkeypatch.setenv("THRIFT_TLS_CL_KEY_PATH", "/must/not/reach/stop")
    outcome = M.exact_deployment_stop(types.SimpleNamespace(stop=Stop))
    assert outcome["attempted"] is True
    assert outcome["completed"] is completed
    if category is None:
        assert outcome["returncode"] == 0
        assert "category" not in outcome
    else:
        assert outcome["category"] == category
    assert observed["argv"] == [M.DEPLOYMENT_ID]
    assert observed["environment"]["V2_DEPLOYMENTS_ROOT"] == str(root)
    assert "THRIFT_TLS_CL_KEY_PATH" not in observed["environment"]
    assert observed["prune_was_replaced"] is True
    assert observed["prune_result"] == 0
    assert os.environ["THRIFT_TLS_CL_KEY_PATH"] == "/must/not/reach/stop"
    assert Stop.paths.prune_removed_dir is original_prune
    after = (M.signature(stale.lstat()), M.signature(stale_record.lstat()), stale_record.read_bytes())
    assert after == before


def test_terminal_proof_rejects_lingering_step(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = iter(
        [
            result(stdout=b""),
            result(stdout=b"123|CANCELLED|\n123.batch|RUNNING|\n"),
        ]
        * 20
    )
    monkeypatch.setattr(M, "run_command", lambda *_args, **_kwargs: next(outputs))
    ticks = iter(range(1000))
    monkeypatch.setattr(M.time, "monotonic", lambda: next(ticks) * 100.0)
    monkeypatch.setattr(M.time, "sleep", lambda _delay: None)
    assert M.prove_terminal("123") is False


def test_terminal_proof_requires_six_complete_rounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = iter(
        [
            item
            for _ in range(M.ZERO_ROUNDS)
            for item in (
                result(stdout=b""),
                result(stdout=b"123|CANCELLED|\n123.batch|COMPLETED|\n"),
            )
        ]
    )
    monkeypatch.setattr(M, "run_command", lambda *_args, **_kwargs: next(outputs))
    monkeypatch.setattr(M.time, "sleep", lambda _delay: None)
    assert M.prove_terminal("123") is True


def test_bounded_submit_signal_reaps_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Toggle:
        calls = 0

        def is_set(self) -> bool:
            self.calls += 1
            return self.calls > 1

    monkeypatch.setattr(M, "STOP_EVENT", Toggle())
    outcome, _code, _output, terminal = M.bounded_submit(
        [
            "/usr/bin/python3.12",
            "-I",
            "-S",
            "-B",
            "-c",
            "import time;time.sleep(30)",
        ],
        {"HOME": "/nonexistent", "PATH": "/usr/bin:/bin"},
    )
    assert outcome == "signal"
    assert terminal is True


def test_publish_is_no_overwrite() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first = M.publish_exclusive(root, "receipt.json", {"a": 1})
        assert first == hashlib.sha256(b'{"a":1}\n').hexdigest()
        with pytest.raises(FileExistsError):
            M.publish_exclusive(root, "receipt.json", {"a": 2})
        assert (root / "receipt.json").read_bytes() == b'{"a":1}\n'


def test_publish_closes_temporary_descriptor_before_unlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    opened_temporary: set[int] = set()
    closed: set[int] = set()
    real_open = M.os.open
    real_close = M.os.close
    real_unlink = M.os.unlink

    def tracked_open(path: object, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if isinstance(path, str) and path.startswith(".receipt.json.") and path.endswith(".tmp"):
            opened_temporary.add(descriptor)
        return descriptor

    def tracked_close(descriptor: int) -> None:
        closed.add(descriptor)
        real_close(descriptor)

    def tracked_unlink(path: object, *args: object, **kwargs: object) -> None:
        if isinstance(path, str) and path.startswith(".receipt.json.") and path.endswith(".tmp"):
            assert opened_temporary and opened_temporary <= closed
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(M.os, "open", tracked_open)
    monkeypatch.setattr(M.os, "close", tracked_close)
    monkeypatch.setattr(M.os, "unlink", tracked_unlink)
    M.publish_exclusive(tmp_path, "receipt.json", {"a": 1})
    assert opened_temporary <= closed


def test_checkpoint_nfs_publication_and_terminal_tombstone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(tempfile.mkdtemp(prefix=".v12b-nfs-regression-", dir=M.BUNDLE.parent))
    root.chmod(0o700)
    try:
        first_sha = M.publish_exclusive(root, "first.json", {"first": 1})
        second_sha = M.publish_exclusive(root, "second.json", {"second": 2})
        assert first_sha == hashlib.sha256(b'{"first":1}\n').hexdigest()
        assert second_sha == hashlib.sha256(b'{"second":2}\n').hexdigest()
        assert (root / "first.json").stat().st_nlink == 1
        assert (root / "second.json").stat().st_nlink == 1
        assert not any(path.name.startswith(".nfs") or path.name.endswith(".tmp") for path in root.iterdir())

        lock = root / "private.global.lock"
        sibling = root / "benign-sibling"
        monkeypatch.setattr(M, "GLOBAL_LOCK", lock)
        handle = M.acquire_global_lock()
        sibling.write_bytes(b"sibling")
        M.validate_global_lock(handle)
        proof = M.finalize_global_lock(handle, outcome="commit_pending", error_code="none")
        assert M.inode_identity(lock.stat()) == (proof.device, proof.inode)
        assert json.loads(lock.read_text())["state"] == "terminal_commit_pending"
        assert sibling.read_bytes() == b"sibling"

        monkeypatch.setattr(M, "ROUTE_ROOT", root)
        monkeypatch.setattr(M, "COMMIT_MARKER", root / "ready_commit.json")
        commit_source, commit_sha, commit_payload = M.prepare_ready_commit(
            intent_sha="1" * 64,
            initial_sha="2" * 64,
            resolved_sha="3" * 64,
            route_policy_sha="4" * 64,
            launch_sha="5" * 64,
            readiness_sha="6" * 64,
            route_binding_sha="7" * 64,
            lock_proof=proof,
            coordinator="101",
            standby="102",
            workers=["201", "202"],
            proxy_job="203",
        )
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            os.link(
                commit_source.name,
                M.COMMIT_MARKER.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        marker_status = M.COMMIT_MARKER.stat()
        source_status = commit_source.stat()
        assert M.signature(marker_status) == M.signature(source_status)
        assert marker_status.st_nlink == 2
        assert M.COMMIT_MARKER.read_bytes() == M.canonical_bytes(commit_payload)
        assert hashlib.sha256(M.COMMIT_MARKER.read_bytes()).hexdigest() == commit_sha
        assert not any(path.name.startswith(".nfs") or path.name.endswith(".tmp") for path in root.iterdir())
    finally:
        for path in root.iterdir():
            path.unlink()
        root.rmdir()


@pytest.mark.parametrize(
    "raw,error",
    (
        (b'{"a":1,"a":2}\n', "artifact_duplicate_key"),
        (b'{"a": 1}\n', "commit_marker"),
    ),
)
def test_ready_commit_rejects_duplicate_or_noncanonical_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: bytes, error: str
) -> None:
    route = tmp_path / "route"
    route.mkdir(mode=0o700)
    source = route / (".ready_commit." + "a" * 32 + ".source.json")
    source.write_bytes(raw)
    source.chmod(0o400)
    marker = route / "ready_commit.json"
    os.link(source, marker)
    monkeypatch.setattr(M, "ROUTE_ROOT", route)
    monkeypatch.setattr(M, "COMMIT_MARKER", marker)
    with pytest.raises(M.DeploymentError, match=error):
        M.validate_ready_commit()


def test_publish_detects_parent_directory_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        root = base / "root"
        replacement = base / "replacement"
        old = base / "old"
        root.mkdir(mode=0o700)
        replacement.mkdir(mode=0o700)
        real_link = M.os.link

        def swapping_link(*args, **kwargs):
            root.rename(old)
            replacement.rename(root)
            return real_link(*args, **kwargs)

        monkeypatch.setattr(M.os, "link", swapping_link)
        with pytest.raises(M.DeploymentError, match="publish_directory_race"):
            M.publish_exclusive(root, "receipt.json", {"a": 1})
        assert not (root / "receipt.json").exists()
        assert (old / "receipt.json").read_bytes() == b'{"a":1}\n'


def test_status_schema_requires_exact_two_ready_routes() -> None:
    status = {
        "schema_version": 4,
        "deployment_id": M.DEPLOYMENT_ID,
        "phase": "serving",
        "endpoints_summary": {
            "desired": 2,
            "ready": 2,
            "pending": 0,
            "running_not_ready": 0,
        },
        "coord": {"jobid": "100", "ticks_completed": 2},
        "spec": {
            "model": M.MODEL_SELECTOR,
            "served_model_name": M.MODEL,
            "num_endpoints_desired": 2,
            "gpu_partition": "g3",
            "account": "ram",
            "qos": M.WORKER_QOS,
            "gpus_per_endpoint": 16,
        },
        "endpoints": [
            {
                "jobid": "101",
                "slurm_state": "RUNNING",
                "sub_state": "ready",
                "host": "redacted",
                "port": 1,
            },
            {
                "jobid": "102",
                "slurm_state": "RUNNING",
                "sub_state": "ready",
                "host": "redacted",
                "port": 2,
            },
        ],
        "proxy": {"jobid": "103", "slurm_state": "RUNNING", "url": "redacted"},
    }
    status["proxy"] = {
        "jobid": "103",
        "slurm_state": "RUNNING",
        "url": "http://redacted",
        "extras": {
            "proxy_type": "litellm",
            "prometheus_port": 8000,
            "sticky": True,
            "sticky_ttl": 14_400,
            "redis_port": 9000,
        },
    }
    assert M.validate_status(status, "100") == (["101", "102"], "103")
    status["endpoints"][1]["host"] = status["endpoints"][0]["host"]
    status["endpoints"][1]["port"] = status["endpoints"][0]["port"]
    with pytest.raises(M.DeploymentError, match="status_job_ids"):
        M.validate_status(status, "100")
    status["endpoints"][1]["host"] = "redacted-2"
    status["endpoints"][1]["port"] = 2
    del status["proxy"]["extras"]["redis_port"]
    with pytest.raises(M.DeploymentError, match="status_proxy"):
        M.validate_status(status, "100")
    status["proxy"]["extras"]["redis_port"] = 9000
    status["endpoints_summary"]["ready"] = 1
    with pytest.raises(M.DeploymentError, match="status_contract"):
        M.validate_status(status, "100")


def test_global_lock_identity_rejects_named_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        lock = Path(directory) / "lock"
        monkeypatch.setattr(M, "GLOBAL_LOCK", lock)
        handle = M.acquire_global_lock()
        M.validate_global_lock(handle)
        replacement = Path(directory) / "replacement"
        replacement.write_bytes(b"replacement")
        replacement.chmod(0o600)
        replacement_identity = replacement.stat()
        replacement.replace(lock)
        with pytest.raises(M.DeploymentError, match="global_lock_identity"):
            M.validate_global_lock(handle)
        with pytest.raises(M.DeploymentError, match="global_lock_identity"):
            M.finalize_global_lock(handle, outcome="failure", error_code="global_lock_identity")
        assert lock.read_bytes() == b"replacement"
        assert M.inode_identity(lock.stat()) == M.inode_identity(replacement_identity)


def test_global_lock_is_exclusively_created_and_never_adopted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lock = tmp_path / "lock"
    monkeypatch.setattr(M, "GLOBAL_LOCK", lock)
    observed_flags: list[int] = []
    real_open = M.os.open

    def tracked_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == lock.name and dir_fd is not None:
            observed_flags.append(flags)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(M.os, "open", tracked_open)
    handle = M.acquire_global_lock()
    with pytest.raises(M.DeploymentError, match="global_lock_exists"):
        M.acquire_global_lock()
    M.validate_global_lock(handle)
    proof = M.finalize_global_lock(handle, outcome="commit_pending", error_code="none")
    assert observed_flags
    assert observed_flags[0] & M.os.O_CREAT
    assert observed_flags[0] & M.os.O_EXCL
    assert observed_flags[0] & M.os.O_NOFOLLOW
    terminal = json.loads(lock.read_text())
    assert terminal["state"] == "terminal_commit_pending"
    assert terminal["error_code"] == "none"
    assert proof.sha256 == hashlib.sha256(M.canonical_bytes(terminal)).hexdigest()
    assert (proof.device, proof.inode) == M.inode_identity(lock.stat())


def test_global_lock_allows_benign_sibling_creation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lock = tmp_path / "lock"
    sibling = tmp_path / "unrelated-sibling"
    monkeypatch.setattr(M, "GLOBAL_LOCK", lock)
    handle = M.acquire_global_lock()
    sibling.write_bytes(b"unrelated")
    M.validate_global_lock(handle)
    proof = M.finalize_global_lock(handle, outcome="failure", error_code="internal_error")
    assert sibling.read_bytes() == b"unrelated"
    assert (proof.device, proof.inode) == M.inode_identity(lock.stat())
    assert json.loads(lock.read_text())["state"] == "terminal_failure"


def bind_fresh_test_namespaces(
    monkeypatch: pytest.MonkeyPatch, root: Path
) -> dict[str, Path]:
    paths = {
        "RUN_ROOT": root / "run",
        "ROUTE_ROOT": root / "route",
        "OUTPUT_ROOT": root / "output",
        "DEPLOYMENT_ROOT": root / "deployment",
        "GLOBAL_LOCK": root / "owner.lock",
        "REMOVED_ROOT": root / "removed",
    }
    paths["REMOVED_ROOT"].mkdir()
    for name, path in paths.items():
        monkeypatch.setattr(M, name, path)
    artifacts = {
        "ROUTE_POLICY": paths["ROUTE_ROOT"] / "route_policy.json",
        "INITIAL_OBSERVATION": paths["RUN_ROOT"] / "initial_spec_observation.json",
        "RESOLVED_BINDING": paths["ROUTE_ROOT"] / "resolved_spec_binding.json",
        "LAUNCH_RECEIPT": paths["RUN_ROOT"] / "deployment_receipt.json",
        "READINESS": paths["ROUTE_ROOT"] / "readiness.json",
        "ROUTE_BINDING": paths["ROUTE_ROOT"] / "live_route_binding.json",
        "COMMIT_MARKER": paths["ROUTE_ROOT"] / "ready_commit.json",
        "CLEANUP_RECEIPT": paths["RUN_ROOT"] / "cleanup_receipt.json",
    }
    for name, path in artifacts.items():
        monkeypatch.setattr(M, name, path)
    paths.update(artifacts)
    monkeypatch.setattr(M, "prove_name_absent", lambda *args, **kwargs: None)
    return paths


def test_preexisting_global_lock_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = bind_fresh_test_namespaces(monkeypatch, tmp_path)
    paths["GLOBAL_LOCK"].write_bytes(b"preexisting")
    paths["GLOBAL_LOCK"].chmod(0o600)
    identity = paths["GLOBAL_LOCK"].stat()
    with pytest.raises(M.DeploymentError, match="namespace_exists"):
        M.assert_paths_fresh()
    with pytest.raises(M.DeploymentError, match="global_lock_exists"):
        M.acquire_global_lock()
    assert paths["GLOBAL_LOCK"].read_bytes() == b"preexisting"
    assert M.inode_identity(paths["GLOBAL_LOCK"].stat()) == M.inode_identity(identity)


def test_preexisting_global_lock_symlink_is_retained(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = bind_fresh_test_namespaces(monkeypatch, tmp_path)
    target = tmp_path / "target"
    target.write_bytes(b"do-not-touch")
    paths["GLOBAL_LOCK"].symlink_to(target)
    with pytest.raises(M.DeploymentError, match="global_lock_exists"):
        M.acquire_global_lock()
    assert paths["GLOBAL_LOCK"].is_symlink()
    assert paths["GLOBAL_LOCK"].readlink() == target
    assert target.read_bytes() == b"do-not-touch"


def test_failed_flock_retains_terminal_tombstone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = bind_fresh_test_namespaces(monkeypatch, tmp_path)

    def fail_flock(_descriptor: int, _operation: int) -> None:
        raise OSError(errno.EWOULDBLOCK, "busy")

    monkeypatch.setattr(M.fcntl, "flock", fail_flock)
    with pytest.raises(M.DeploymentError, match="global_lock_busy"):
        M.acquire_global_lock()
    terminal = json.loads(paths["GLOBAL_LOCK"].read_text())
    assert terminal["state"] == "terminal_failure"
    assert terminal["error_code"] == "global_lock_busy"


@pytest.mark.parametrize("race_after_freshness", (False, True))
def test_execute_rejects_preexisting_or_raced_lock_before_submission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    race_after_freshness: bool,
) -> None:
    paths = bind_fresh_test_namespaces(monkeypatch, tmp_path)
    for name in (
        "validate_cli_environment",
        "validate_root_runtime",
        "validate_tmux_ancestry",
        "validate_source",
        "validate_evaluator",
    ):
        monkeypatch.setattr(M, name, lambda *args, **kwargs: None)
    bundle_hashes = expected_bundle_hashes()
    approval_sha, approval_payload = expected_approval(bundle_hashes)
    approval_active = True
    approval_checks = 0

    def validate_approval(_hashes: dict[str, str]):
        nonlocal approval_checks
        approval_checks += 1
        if not approval_active:
            raise M.DeploymentError("approval_unavailable")
        return approval_sha, approval_payload

    monkeypatch.setattr(M, "validate_bundle", lambda _raw: bundle_hashes)
    monkeypatch.setattr(M, "validate_approval", validate_approval)
    monkeypatch.setattr(M, "validate_runtime_zip", lambda *_args: b"runtime")
    monkeypatch.setattr(M, "validate_serving_runtime", lambda: M.SERVING_RUNTIME_MANIFESTS)
    monkeypatch.setattr(M, "model_provenance", lambda: {})
    monkeypatch.setattr(
        M,
        "derive_worker_qos_preemptors",
        lambda: M.EXPECTED_WORKER_QOS_PREEMPTORS,
    )
    monkeypatch.setattr(M, "registry_tls_binding", lambda: {})
    submitted: list[bool] = []
    monkeypatch.setattr(M, "load_serve_api", lambda _raw: submitted.append(True))
    real_freshness = M.assert_paths_fresh

    def create_raced_lock() -> None:
        paths["GLOBAL_LOCK"].write_bytes(b"raced")
        paths["GLOBAL_LOCK"].chmod(0o600)

    if not race_after_freshness:
        create_raced_lock()
    else:
        calls = 0

        def race(*, held_global_lock: M.GlobalLock | None = None) -> None:
            nonlocal calls
            real_freshness(held_global_lock=held_global_lock)
            calls += 1
            if calls == 1:
                create_raced_lock()

        monkeypatch.setattr(M, "assert_paths_fresh", race)
    identity = paths["GLOBAL_LOCK"].stat() if paths["GLOBAL_LOCK"].exists() else None
    with pytest.raises(M.DeploymentError, match="namespace_exists|global_lock_exists"):
        M.execute(b"controller")
    if identity is None:
        identity = paths["GLOBAL_LOCK"].stat()
    assert submitted == []
    assert paths["GLOBAL_LOCK"].read_bytes() == b"raced"
    assert M.inode_identity(paths["GLOBAL_LOCK"].stat()) == M.inode_identity(identity)


@pytest.mark.parametrize(
    "occupied",
    ("RUN_ROOT", "ROUTE_ROOT", "OUTPUT_ROOT", "DEPLOYMENT_ROOT"),
)
def test_post_lock_freshness_rejects_every_other_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, occupied: str
) -> None:
    paths = bind_fresh_test_namespaces(monkeypatch, tmp_path)
    handle = M.acquire_global_lock()
    try:
        M.assert_paths_fresh(held_global_lock=handle)
        paths[occupied].mkdir()
        with pytest.raises(M.DeploymentError, match="namespace_exists"):
            M.assert_paths_fresh(held_global_lock=handle)
    finally:
        M.finalize_global_lock(handle, outcome="failure", error_code="namespace_exists")
    assert json.loads(paths["GLOBAL_LOCK"].read_text())["state"] == "terminal_failure"


def test_post_lock_freshness_rejects_archived_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = bind_fresh_test_namespaces(monkeypatch, tmp_path)
    archived = paths["REMOVED_ROOT"] / f"{M.DEPLOYMENT_ID}-old"
    archived.mkdir()
    handle = M.acquire_global_lock()
    try:
        with pytest.raises(M.DeploymentError, match="archived_namespace_exists"):
            M.assert_paths_fresh(held_global_lock=handle)
    finally:
        M.finalize_global_lock(handle, outcome="failure", error_code="archived_namespace_exists")
    assert json.loads(paths["GLOBAL_LOCK"].read_text())["state"] == "terminal_failure"


def test_execute_validates_owned_lock_before_creating_namespaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = bind_fresh_test_namespaces(monkeypatch, tmp_path)
    observed: list[tuple[bool, bool]] = []
    real_freshness = M.assert_paths_fresh

    def observe_freshness(*, held_global_lock: M.GlobalLock | None = None) -> None:
        observed.append((held_global_lock is not None, paths["GLOBAL_LOCK"].exists()))
        real_freshness(held_global_lock=held_global_lock)

    for name in (
        "validate_cli_environment",
        "validate_root_runtime",
        "validate_tmux_ancestry",
        "validate_source",
        "validate_evaluator",
    ):
        monkeypatch.setattr(M, name, lambda *args, **kwargs: None)
    bundle_hashes = expected_bundle_hashes()
    approval_sha, approval_payload = expected_approval(bundle_hashes)
    approval_active = True
    approval_checks = 0

    def validate_approval(_hashes: dict[str, str]):
        nonlocal approval_checks
        approval_checks += 1
        if not approval_active:
            raise M.DeploymentError("approval_unavailable")
        return approval_sha, approval_payload

    monkeypatch.setattr(M, "validate_bundle", lambda _raw: bundle_hashes)
    monkeypatch.setattr(M, "validate_approval", validate_approval)
    monkeypatch.setattr(M, "validate_runtime_zip", lambda *_args: b"runtime")
    monkeypatch.setattr(M, "validate_serving_runtime", lambda: M.SERVING_RUNTIME_MANIFESTS)
    monkeypatch.setattr(M, "model_provenance", lambda: {})
    monkeypatch.setattr(
        M,
        "derive_worker_qos_preemptors",
        lambda: M.EXPECTED_WORKER_QOS_PREEMPTORS,
    )
    monkeypatch.setattr(M, "registry_tls_binding", lambda: {})
    monkeypatch.setattr(M, "assert_paths_fresh", observe_freshness)
    monkeypatch.setattr(
        M,
        "load_serve_api",
        lambda _raw: (_ for _ in ()).throw(RuntimeError("stop_after_lock_order")),
    )
    monkeypatch.setattr(
        M,
        "cleanup",
        lambda *_args: {
            "all_terminal": True,
            "namespace_archived": True,
        },
    )
    monkeypatch.setattr(M, "CURRENT_API", None)
    monkeypatch.setattr(M, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(M, "COORDINATOR_RELEASED", False)
    with pytest.raises(RuntimeError, match="stop_after_lock_order"):
        M.execute(b"controller")
    assert observed[:2] == [(False, False), (True, True)]
    assert paths["RUN_ROOT"].is_dir()
    assert paths["ROUTE_ROOT"].is_dir()
    terminal = json.loads(paths["GLOBAL_LOCK"].read_text())
    assert terminal["state"] == "terminal_failure"
    assert terminal["error_code"] == "internal_error"
    for artifact in (paths["GLOBAL_LOCK"], paths["CLEANUP_RECEIPT"], paths["RUN_ROOT"] / "failure.json"):
        raw = artifact.read_bytes()
        assert b"stop_after_lock_order" not in raw
        assert json.loads(raw)["error_code"] == "internal_error"


@pytest.mark.parametrize(
    "interrupt_at",
    (
        "success",
        "approval_removed_before_consumption",
        "final_validation",
        "readiness_publish",
        "route_publish",
        "before_commit",
        "lock_replacement",
        "lock_replacement_during_finalize",
        "no_path_mutation",
        "commit_link_then_raise",
        "commit_link_fstat_failure",
        "commit_link_close_failure",
        "commit_link_absent",
        "commit_link_delayed_visibility",
        "commit_link_conflict",
    ),
)
def test_execute_terminal_lock_and_commit_linearization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    interrupt_at: str,
) -> None:
    paths = bind_fresh_test_namespaces(monkeypatch, tmp_path)
    assert not any(
        paths[name].exists()
        for name in ("RUN_ROOT", "ROUTE_ROOT", "OUTPUT_ROOT", "DEPLOYMENT_ROOT", "GLOBAL_LOCK")
    )
    for name in (
        "validate_cli_environment",
        "validate_root_runtime",
        "validate_tmux_ancestry",
        "validate_source",
        "validate_evaluator",
        "validate_import_origins",
        "coordinator_identity",
        "service_job_identity",
        "release_job",
        "close_serve_api",
    ):
        monkeypatch.setattr(M, name, lambda *args, **kwargs: None)
    bundle_hashes = expected_bundle_hashes()
    approval_sha, approval_payload = expected_approval(bundle_hashes)
    approval_active = True
    approval_checks = 0

    def validate_approval(_hashes: dict[str, str]):
        nonlocal approval_checks
        approval_checks += 1
        if not approval_active or (
            interrupt_at == "approval_removed_before_consumption" and approval_checks == 2
        ):
            raise M.DeploymentError("approval_unavailable")
        return approval_sha, approval_payload

    monkeypatch.setattr(M, "validate_bundle", lambda _raw: bundle_hashes)
    monkeypatch.setattr(M, "validate_approval", validate_approval)
    monkeypatch.setattr(M, "validate_runtime_zip", lambda *_args: b"runtime")
    monkeypatch.setattr(M, "validate_serving_runtime", lambda: M.SERVING_RUNTIME_MANIFESTS)
    monkeypatch.setattr(M, "model_provenance", lambda: {})
    monkeypatch.setattr(
        M,
        "derive_worker_qos_preemptors",
        lambda: M.EXPECTED_WORKER_QOS_PREEMPTORS,
    )
    monkeypatch.setattr(M, "registry_tls_binding", lambda: {})
    monkeypatch.setattr(M, "load_serve_api", lambda _raw: object())
    monkeypatch.setattr(M, "run_explain", lambda _api: M.EXPLAIN_NORMALIZED_SHA256)

    def deploy(_api: object, _token: str) -> tuple[int, bytes, bytes]:
        M.SUBMITTED_JOB_ID = "100"
        return 0, b"", b""

    def observe(_api: object, *, final: bool) -> tuple[str, str]:
        if final:
            return "f" * 64, M.FINAL_SPEC_NORMALIZED_SHA256
        return "i" * 64, M.INITIAL_SPEC_NORMALIZED_SHA256

    cleanup_calls: list[tuple[str, list[str]]] = []

    def clean(token: str, known: list[str]) -> dict[str, object]:
        cleanup_calls.append((token, list(known)))
        return {"all_terminal": True, "namespace_archived": True}

    def final_validation(_api: object, **_kwargs: object) -> int:
        if interrupt_at == "final_validation":
            M.STOP_EVENT.set()
        return 43

    real_publish = M.publish_exclusive

    def publish(
        directory: Path,
        name: str,
        payload: dict[str, object],
        mode: int = 0o400,
    ) -> str:
        nonlocal approval_active
        digest = real_publish(directory, name, payload, mode)
        if name == "owner_intent.json":
            approval_active = False
        if (
            (interrupt_at == "readiness_publish" and name == paths["READINESS"].name)
            or (interrupt_at == "route_publish" and name == paths["ROUTE_BINDING"].name)
        ):
            M.STOP_EVENT.set()
        return digest

    real_consume = M.consume_readiness

    def consume(*args: object, **kwargs: object) -> str:
        digest = real_consume(*args, **kwargs)
        if interrupt_at == "before_commit":
            M.STOP_EVENT.set()
        return digest

    real_finalize = M.finalize_global_lock
    replacement_identity: list[tuple[int, int]] = []
    owned_identity: list[tuple[int, int]] = []
    owned_descriptor: list[int] = []

    def finalize(lock: M.GlobalLock, *, outcome: str, error_code: str) -> M.TerminalLockProof:
        owned_identity.append(lock.identity)
        owned_descriptor.append(lock.descriptor)
        if interrupt_at == "lock_replacement":
            replacement = tmp_path / "replacement.lock"
            replacement.write_bytes(b"replacement")
            replacement.chmod(0o600)
            replacement_identity.append(M.inode_identity(replacement.stat()))
            replacement.replace(paths["GLOBAL_LOCK"])
        return real_finalize(lock, outcome=outcome, error_code=error_code)

    real_ftruncate = M.os.ftruncate

    def ftruncate(descriptor: int, length: int) -> None:
        real_ftruncate(descriptor, length)
        if (
            interrupt_at == "lock_replacement_during_finalize"
            and owned_descriptor
            and descriptor == owned_descriptor[0]
            and not replacement_identity
        ):
            replacement = tmp_path / "replacement-during-finalize.lock"
            replacement.write_bytes(b"replacement-during-finalize")
            replacement.chmod(0o600)
            replacement_identity.append(M.inode_identity(replacement.stat()))
            replacement.replace(paths["GLOBAL_LOCK"])

    real_rename = M.os.rename
    real_unlink = M.os.unlink
    real_link = M.os.link
    real_fstat = M.os.fstat
    real_stat = M.os.stat
    real_open = M.os.open
    real_close = M.os.close
    marker_linked = False
    source_descriptors: set[int] = set()
    fstat_failed = False
    close_failed = False
    marker_visibility_delayed = False

    def rename(source: object, target: object, *args: object, **kwargs: object) -> None:
        if interrupt_at == "no_path_mutation" and (
            os.fspath(source) == paths["GLOBAL_LOCK"].name
            or os.fspath(target) == paths["GLOBAL_LOCK"].name
        ):
            raise AssertionError("global lock rename attempted")
        real_rename(source, target, *args, **kwargs)

    def unlink(path: object, *args: object, **kwargs: object) -> None:
        if interrupt_at == "no_path_mutation" and os.fspath(path) == paths["GLOBAL_LOCK"].name:
            raise AssertionError("global lock unlink attempted")
        real_unlink(path, *args, **kwargs)

    def link(source: object, target: object, *args: object, **kwargs: object) -> None:
        nonlocal marker_linked
        if os.fspath(target) != paths["COMMIT_MARKER"].name:
            real_link(source, target, *args, **kwargs)
            return
        if interrupt_at == "commit_link_absent":
            raise OSError(errno.EIO, "injected absent reply")
        if interrupt_at == "commit_link_conflict":
            conflict = paths["ROUTE_ROOT"] / ".conflicting-marker"
            conflict.write_bytes(b"conflict\n")
            conflict.chmod(0o400)
            real_link(conflict, paths["COMMIT_MARKER"])
            marker_linked = True
            raise FileExistsError(errno.EEXIST, "injected conflicting marker")
        real_link(source, target, *args, **kwargs)
        marker_linked = True
        if interrupt_at in {
            "commit_link_then_raise",
            "commit_link_fstat_failure",
            "commit_link_delayed_visibility",
        }:
            raise OSError(errno.EIO, "injected ambiguous reply")

    def tracked_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if isinstance(path, str) and path.startswith(".ready_commit.") and path.endswith(".source.json"):
            source_descriptors.add(descriptor)
        return descriptor

    def fstat(descriptor: int) -> os.stat_result:
        nonlocal fstat_failed
        if interrupt_at == "commit_link_fstat_failure" and marker_linked and not fstat_failed:
            fstat_failed = True
            raise OSError(errno.EIO, "injected fstat ambiguity")
        return real_fstat(descriptor)

    def tracked_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal marker_visibility_delayed
        if (
            interrupt_at == "commit_link_delayed_visibility"
            and marker_linked
            and os.fspath(path) == paths["COMMIT_MARKER"].name
            and not marker_visibility_delayed
        ):
            marker_visibility_delayed = True
            raise FileNotFoundError(errno.ENOENT, "injected delayed visibility")
        return real_stat(path, *args, **kwargs)

    def close(descriptor: int) -> None:
        nonlocal close_failed
        if (
            interrupt_at == "commit_link_close_failure"
            and marker_linked
            and descriptor in source_descriptors
            and not close_failed
        ):
            close_failed = True
            real_close(descriptor)
            raise OSError(errno.EIO, "injected close ambiguity")
        real_close(descriptor)

    monkeypatch.setattr(M, "run_deploy", deploy)
    monkeypatch.setattr(M, "observe_stable_spec", observe)
    monkeypatch.setattr(M, "content_tree_manifest", lambda _path: M.SNAPSHOT_MANIFEST)
    monkeypatch.setattr(M, "wait_for_serving", lambda *_args: (["201", "202"], "203", 42))
    monkeypatch.setattr(M, "standby_identity", lambda *_args, **_kwargs: "101")
    monkeypatch.setattr(
        M,
        "validate_spec",
        lambda *_args, **_kwargs: ("f" * 64, M.FINAL_SPEC_NORMALIZED_SHA256),
    )
    monkeypatch.setattr(M, "validate_live_generation", final_validation)
    monkeypatch.setattr(M, "publish_exclusive", publish)
    monkeypatch.setattr(M, "consume_readiness", consume)
    monkeypatch.setattr(M, "finalize_global_lock", finalize)
    monkeypatch.setattr(M.os, "ftruncate", ftruncate)
    monkeypatch.setattr(M.os, "rename", rename)
    monkeypatch.setattr(M.os, "unlink", unlink)
    monkeypatch.setattr(M.os, "link", link)
    monkeypatch.setattr(M.os, "open", tracked_open)
    monkeypatch.setattr(M.os, "fstat", fstat)
    monkeypatch.setattr(M.os, "stat", tracked_stat)
    monkeypatch.setattr(M.os, "close", close)
    monkeypatch.setattr(M, "cleanup", clean)
    monkeypatch.setattr(M, "CURRENT_API", None)
    monkeypatch.setattr(M, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(M, "SUBMITTED_DIRECT", False)
    monkeypatch.setattr(M, "COORDINATOR_RELEASED", False)
    M.STOP_EVENT.clear()
    try:
        if interrupt_at in {
            "success",
            "no_path_mutation",
            "commit_link_then_raise",
            "commit_link_close_failure",
        }:
            assert M.execute(b"controller") == 0
        elif interrupt_at in {"lock_replacement", "lock_replacement_during_finalize"}:
            with pytest.raises(M.DeploymentError, match="global_lock_identity|global_lock_finalize"):
                M.execute(b"controller")
        elif interrupt_at == "commit_link_fstat_failure":
            with pytest.raises(M.DeploymentError, match="commit_link_ambiguous"):
                M.execute(b"controller")
        elif interrupt_at == "commit_link_absent":
            with pytest.raises(M.DeploymentError, match="commit_link_ambiguous_absent"):
                M.execute(b"controller")
        elif interrupt_at == "commit_link_delayed_visibility":
            with pytest.raises(M.DeploymentError, match="commit_link_ambiguous_absent"):
                M.execute(b"controller")
        elif interrupt_at == "commit_link_conflict":
            with pytest.raises(M.DeploymentError, match="commit_link_conflict"):
                M.execute(b"controller")
        elif interrupt_at == "approval_removed_before_consumption":
            with pytest.raises(M.DeploymentError, match="approval_unavailable"):
                M.execute(b"controller")
        else:
            with pytest.raises(M.LaunchCancelled):
                M.execute(b"controller")
    finally:
        M.STOP_EVENT.clear()
    captured = capsys.readouterr()
    assert approval_checks == 2
    if interrupt_at in {
        "success",
        "no_path_mutation",
        "commit_link_then_raise",
        "commit_link_close_failure",
    }:
        assert cleanup_calls == []
        assert json.loads(captured.out)["state"] == "ready_for_smoke"
        intent = json.loads((paths["RUN_ROOT"] / "owner_intent.json").read_text())
        assert intent["approval_sha256"] == approval_sha
        assert intent["approval_payload"] == approval_payload
        assert paths["READINESS"].exists()
        assert paths["ROUTE_BINDING"].exists()
        assert json.loads(paths["READINESS"].read_text())["promotion_eligible"] is False
        assert json.loads(paths["ROUTE_BINDING"].read_text())["promotion_eligible"] is False
        assert json.loads(paths["COMMIT_MARKER"].read_text())["state"] == "ready_for_smoke"
        marker_status = paths["COMMIT_MARKER"].stat()
        marker_payload = M.validate_ready_commit()
        source_status = (paths["ROUTE_ROOT"] / marker_payload["commit_source_name"]).stat()
        assert M.signature(marker_status) == M.signature(source_status)
        assert marker_status.st_nlink == 2
        terminal = json.loads(paths["GLOBAL_LOCK"].read_text())
        assert terminal["state"] == "terminal_commit_pending"
        assert terminal["error_code"] == "none"
    elif interrupt_at in {
        "commit_link_fstat_failure",
        "commit_link_conflict",
        "commit_link_absent",
        "commit_link_delayed_visibility",
    }:
        assert cleanup_calls == []
        assert captured.out == ""
        assert paths["COMMIT_MARKER"].exists() is (interrupt_at != "commit_link_absent")
        assert paths["READINESS"].exists()
        assert paths["ROUTE_BINDING"].exists()
        assert json.loads(paths["GLOBAL_LOCK"].read_text())["state"] == "terminal_commit_pending"
    else:
        assert captured.out == ""
        assert len(cleanup_calls) == 1
        if interrupt_at in {"approval_removed_before_consumption", "final_validation"}:
            assert not paths["READINESS"].exists()
            assert not paths["ROUTE_BINDING"].exists()
        elif interrupt_at == "readiness_publish":
            assert paths["READINESS"].exists()
            assert not paths["ROUTE_BINDING"].exists()
        else:
            assert paths["READINESS"].exists()
            assert paths["ROUTE_BINDING"].exists()
        for artifact in (paths["READINESS"], paths["ROUTE_BINDING"]):
            if artifact.exists():
                assert json.loads(artifact.read_text())["promotion_eligible"] is False
        assert paths["CLEANUP_RECEIPT"].exists()
        cleanup_receipt = json.loads(paths["CLEANUP_RECEIPT"].read_text())
        assert cleanup_receipt["cleanup"]["commit_marker_absent"] is True
        assert cleanup_receipt["error_code"] in {
            "signal",
            "global_lock_identity",
            "approval_unavailable",
        }
        assert not paths["COMMIT_MARKER"].exists()
        if interrupt_at == "lock_replacement":
            assert paths["GLOBAL_LOCK"].read_bytes() == b"replacement"
            assert M.inode_identity(paths["GLOBAL_LOCK"].stat()) == replacement_identity[0]
        elif interrupt_at == "lock_replacement_during_finalize":
            assert paths["GLOBAL_LOCK"].read_bytes() == b"replacement-during-finalize"
            assert M.inode_identity(paths["GLOBAL_LOCK"].stat()) == replacement_identity[0]
        elif interrupt_at == "approval_removed_before_consumption":
            assert M.SUBMITTED_JOB_ID is None
            assert not (paths["RUN_ROOT"] / "owner_intent.json").exists()
            terminal = json.loads(paths["GLOBAL_LOCK"].read_text())
            assert terminal["state"] == "terminal_failure"
            assert terminal["error_code"] == "approval_unavailable"
        else:
            terminal = json.loads(paths["GLOBAL_LOCK"].read_text())
            assert terminal["state"] == "terminal_signal"
            assert terminal["error_code"] == "signal"


def test_failed_namespace_archive_is_no_overwrite_and_anchored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "deployments"
        removed = root / ".removed"
        deployment_id = "fresh-deployment"
        deployment = root / deployment_id
        root.mkdir()
        removed.mkdir()
        deployment.mkdir()
        root.chmod(0o2775)
        removed.chmod(0o2775)
        monkeypatch.setattr(M, "DEPLOYMENTS_ROOT", root)
        monkeypatch.setattr(M, "REMOVED_ROOT", removed)
        monkeypatch.setattr(M, "DEPLOYMENT_ID", deployment_id)
        monkeypatch.setattr(M, "DEPLOYMENT_ROOT", deployment)
        monkeypatch.setattr(M, "MODEL_OWNER_UID", M.os.getuid())
        monkeypatch.setattr(M, "MODEL_OWNER_GID", M.os.getgid())
        assert M.archive_failed_namespace() is True
        assert not deployment.exists()
        archived = list(removed.iterdir())
        assert len(archived) == 1
        assert archived[0].name.startswith(deployment_id + "-")


def test_launcher_and_documented_bootstrap_are_syntax_valid() -> None:
    result_shell = subprocess.run(["/usr/bin/bash", "-n", str(M.LAUNCHER)], capture_output=True, check=False)
    assert result_shell.returncode == 0, result_shell.stderr.decode()
    text = M.README.read_text()
    assert "audit" in text and "execute" in text
    assert "independent approval" in text


def test_direct_entrypoint_is_inert() -> None:
    before = {
        str(path)
        for path in (
            M.APPROVAL,
            M.RUN_ROOT,
            M.ROUTE_ROOT,
            M.GLOBAL_LOCK,
            M.DEPLOYMENT_ROOT,
        )
        if path.exists()
    }
    completed = subprocess.run(
        ["/usr/bin/python3.12", "-I", "-S", "-B", str(CONTROLLER)],
        env={
            "HOME": "/nonexistent",
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "TZ": "UTC",
        },
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {"state": "inert", "launch_eligible": False}
    after = {
        str(path)
        for path in (
            M.APPROVAL,
            M.RUN_ROOT,
            M.ROUTE_ROOT,
            M.GLOBAL_LOCK,
            M.DEPLOYMENT_ROOT,
        )
        if path.exists()
    }
    assert before == after


def test_no_bytecode_or_cache_artifacts() -> None:
    forbidden = []
    for root in (M.BUNDLE, M.SERVE_ROOT):
        forbidden.extend(root.rglob("*.pyc"))
        forbidden.extend(root.rglob("*.pyo"))
        forbidden.extend(root.rglob("__pycache__"))
        forbidden.extend(root.rglob(".pytest_cache"))
        forbidden.extend(root.rglob(".ruff_cache"))
    assert forbidden == []


def test_fresh_namespace_is_disjoint_from_stale_deployments() -> None:
    old = "tianhaowu-k3-kda-tb4-eval-20260919t215851z"
    assert M.DEPLOYMENT_ID not in M.STALE_DEPLOYMENT_IDS
    assert old in M.STALE_DEPLOYMENT_IDS
    assert old not in M.DEPLOY_ARGS
    assert all(
        not M.DEPLOYMENT_ID.startswith(stale + "-") and not stale.startswith(M.DEPLOYMENT_ID + "-")
        for stale in M.STALE_DEPLOYMENT_IDS
    )


def test_success_receipt_and_readiness_are_cross_bound() -> None:
    source = M.CONTROLLER.read_text()
    assert '"promotion_eligible": False' in source
    assert '"next_gate": "cross_bound_readiness"' in source
    assert '"contains_endpoint_or_secret": False' in source
    assert "deployment_receipt.json" in source
    assert "initial_spec_observation.json" in source
    assert "resolved_spec_binding.json" in source
    assert "live_route_binding.json" in source


def test_signal_set_is_bounded() -> None:
    M.STOP_EVENT.clear()
    M.signal_handler(signal.SIGTERM, None)
    assert M.STOP_EVENT.is_set()
    M.STOP_EVENT.clear()


def test_python_runtime_archive_is_closed_before_import() -> None:
    assert hashlib.sha256(M.PYTHON_RUNTIME_TAR.read_bytes()).hexdigest() == (M.PYTHON_RUNTIME_TAR_SHA256)
    with tarfile.open(M.PYTHON_RUNTIME_TAR) as archive:
        members = archive.getmembers()
    assert members
    assert all(member.name == "runtime" or member.name.startswith("runtime/") for member in members)
    assert all(not member.issym() and not member.islnk() for member in members)
    assert all(
        not member.name.endswith((".pth", ".pyc", ".pyo")) and "/__pycache__/" not in member.name for member in members
    )
    assert "--no-same-owner --same-permissions" in M.LAUNCHER.read_text()


def test_g3_lowest_preemptibility_is_derived_from_inbound_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = "\n".join(
        [
            "normal|0|",
            "g3_lowest|1|normal",
            *[f"{name}|100|g3_lowest" for name in M.EXPECTED_WORKER_QOS_PREEMPTORS],
        ]
    ).encode()
    outputs = iter(
        (
            result(stdout=rows),
            result(stdout=b"PreemptType              = preempt/qos\nPreemptMode              = REQUEUE\n"),
        )
    )
    monkeypatch.setattr(M, "run_command", lambda *_args, **_kwargs: next(outputs))
    assert M.derive_worker_qos_preemptors() == M.EXPECTED_WORKER_QOS_PREEMPTORS
    assert M.WORKER_QOS_PREEMPTIBLE is True


def test_g3_lowest_empty_inbound_set_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        M,
        "run_command",
        lambda *_args, **_kwargs: result(stdout=b"normal|0|\ng3_lowest|1|normal\n"),
    )
    with pytest.raises(M.DeploymentError, match="worker_qos_preemption_changed"):
        M.derive_worker_qos_preemptors()


@pytest.mark.parametrize(
    "row",
    (
        b"g3_lowest|0|normal\n",
        b"g3_lowest|1|\n",
        b"g3_lowest|1|normal,g3_core_shared\n",
    ),
)
def test_g3_lowest_priority_and_outbound_set_are_exact(monkeypatch: pytest.MonkeyPatch, row: bytes) -> None:
    monkeypatch.setattr(M, "run_command", lambda *_args, **_kwargs: result(stdout=row))
    with pytest.raises(M.DeploymentError, match="worker_qos_semantics_changed"):
        M.derive_worker_qos_preemptors()


def test_initial_spec_observation_requires_two_identical_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        M,
        "validate_spec",
        lambda *_args, **_kwargs: calls.append(1) or ("a" * 64, "b" * 64),
    )
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda _delay: False)
    assert M.observe_stable_spec(object(), final=False) == ("a" * 64, "b" * 64)
    assert len(calls) == 2


def test_initial_spec_transition_between_reads_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = iter((("a" * 64, "b" * 64), ("c" * 64, "d" * 64)))
    monkeypatch.setattr(M, "validate_spec", lambda *_args, **_kwargs: next(values))
    monkeypatch.setattr(M.STOP_EVENT, "wait", lambda _delay: False)
    with pytest.raises(M.DeploymentError, match="spec_changed_during_observation"):
        M.observe_stable_spec(object(), final=False)


def artifact_graph() -> tuple[dict[Path, tuple[dict, str]], dict[str, str]]:
    hashes = {
        "intent": "1" * 64,
        "initial": "2" * 64,
        "resolved": "3" * 64,
        "launch": "4" * 64,
        "policy": "5" * 64,
        "spec": "6" * 64,
    }
    jobs = {"coordinator": "101", "standby": "102", "proxy": "203"}
    workers = ["201", "202"]
    artifacts = {
        M.ROUTE_POLICY: (
            M.route_policy_payload(M.EXPECTED_WORKER_QOS_PREEMPTORS),
            hashes["policy"],
        ),
        M.INITIAL_OBSERVATION: (
            {
                "state": "stable_initial_spec_observed",
                "deployment_id": M.DEPLOYMENT_ID,
                "intent_sha256": hashes["intent"],
                "route_policy_sha256": hashes["policy"],
                "coordinator_job": jobs["coordinator"],
                "spec_normalized_sha256": M.INITIAL_SPEC_NORMALIZED_SHA256,
                "stable_reads": 2,
            },
            hashes["initial"],
        ),
        M.RESOLVED_BINDING: (
            {
                "state": "resolved_spec_bound",
                "deployment_id": M.DEPLOYMENT_ID,
                "intent_sha256": hashes["intent"],
                "route_policy_sha256": hashes["policy"],
                "initial_observation_sha256": hashes["initial"],
                "coordinator_job": jobs["coordinator"],
                "spec_sha256": hashes["spec"],
                "spec_normalized_sha256": M.FINAL_SPEC_NORMALIZED_SHA256,
                "source_revision": M.SOURCE_REVISION,
                "source_tree": M.SOURCE_TREE,
                "source_snapshot_manifest": M.SNAPSHOT_MANIFEST,
                "worker_qos": M.WORKER_QOS,
                "worker_qos_priority": M.EXPECTED_WORKER_QOS_PRIORITY,
                "worker_qos_outbound_preempt_targets": list(M.EXPECTED_WORKER_QOS_OUTBOUND),
                "worker_qos_preemptible": True,
                "worker_qos_preemptors": list(M.EXPECTED_WORKER_QOS_PREEMPTORS),
                "worker_exclude_nodes": list(M.WORKER_EXCLUDE_NODES),
            },
            hashes["resolved"],
        ),
        M.LAUNCH_RECEIPT: (
            {
                "state": "live_final_spec_bound",
                "deployment_id": M.DEPLOYMENT_ID,
                "intent_sha256": hashes["intent"],
                "route_policy_sha256": hashes["policy"],
                "initial_observation_sha256": hashes["initial"],
                "resolved_binding_sha256": hashes["resolved"],
                "coordinator_job": jobs["coordinator"],
                "coordinator_standby_job": jobs["standby"],
                "worker_jobs": workers,
                "proxy_job": jobs["proxy"],
                "spec_sha256": hashes["spec"],
                "spec_normalized_sha256": M.FINAL_SPEC_NORMALIZED_SHA256,
            },
            hashes["launch"],
        ),
    }
    return artifacts, {**hashes, **jobs, "workers": workers}


def test_readiness_graph_cross_binds_every_generation_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, values = artifact_graph()
    monkeypatch.setattr(M, "load_json_artifact", lambda path: artifacts[path])
    assert M.validate_generation_artifact_graph(
        intent_sha=values["intent"],
        initial_sha=values["initial"],
        resolved_sha=values["resolved"],
        launch_sha=values["launch"],
        route_policy_sha=values["policy"],
        coordinator=values["coordinator"],
        standby=values["standby"],
        workers=values["workers"],
        proxy_job=values["proxy"],
    ) == (values["spec"], M.FINAL_SPEC_NORMALIZED_SHA256)


def test_readiness_graph_rejects_cross_generation_launch_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts, values = artifact_graph()
    artifacts[M.LAUNCH_RECEIPT][0]["resolved_binding_sha256"] = "f" * 64
    monkeypatch.setattr(M, "load_json_artifact", lambda path: artifacts[path])
    with pytest.raises(M.DeploymentError, match="artifact_graph"):
        M.validate_generation_artifact_graph(
            intent_sha=values["intent"],
            initial_sha=values["initial"],
            resolved_sha=values["resolved"],
            launch_sha=values["launch"],
            route_policy_sha=values["policy"],
            coordinator=values["coordinator"],
            standby=values["standby"],
            workers=values["workers"],
            proxy_job=values["proxy"],
        )


def test_readiness_producer_never_publishes_after_graph_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        M,
        "validate_generation_artifact_graph",
        lambda **_kwargs: (_ for _ in ()).throw(M.DeploymentError("artifact_graph")),
    )
    published = []
    monkeypatch.setattr(M, "publish_exclusive", lambda *_args, **_kwargs: published.append(1))
    with pytest.raises(M.DeploymentError, match="artifact_graph"):
        M.produce_readiness(
            object(),
            token="token",
            intent_sha="1" * 64,
            initial_sha="2" * 64,
            resolved_sha="3" * 64,
            launch_sha="4" * 64,
            route_policy_sha="5" * 64,
            coordinator="101",
            standby="102",
            workers=["201", "202"],
            proxy_job="203",
        )
    assert published == []


def test_readiness_consumer_rejects_swapped_readiness_before_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness = {
        "state": "staged_passed",
        "promotion_eligible": False,
        "deployment_id": M.DEPLOYMENT_ID,
        "intent_sha256": "1" * 64,
        "route_policy_sha256": "5" * 64,
        "initial_observation_sha256": "2" * 64,
        "resolved_binding_sha256": "3" * 64,
        "launch_receipt_sha256": "4" * 64,
        "spec_sha256": "6" * 64,
        "spec_normalized_sha256": M.FINAL_SPEC_NORMALIZED_SHA256,
        "coordinator_job": "101",
        "coordinator_standby_job": "102",
        "worker_jobs": ["201", "202"],
        "proxy_job": "203",
        "coordinator_ticks_completed": 1,
        "model_requests_sent": 0,
        "smoke_jobs_submitted": 0,
    }
    monkeypatch.setattr(M, "load_json_artifact", lambda _path: (readiness, "f" * 64))
    monkeypatch.setattr(
        M,
        "validate_generation_artifact_graph",
        lambda **_kwargs: ("6" * 64, M.FINAL_SPEC_NORMALIZED_SHA256),
    )
    published = []
    monkeypatch.setattr(M, "publish_exclusive", lambda *_args, **_kwargs: published.append(1))
    with pytest.raises(M.DeploymentError, match="readiness_graph"):
        M.consume_readiness(
            object(),
            token="token",
            readiness_sha="7" * 64,
            intent_sha="1" * 64,
            initial_sha="2" * 64,
            resolved_sha="3" * 64,
            launch_sha="4" * 64,
            route_policy_sha="5" * 64,
            coordinator="101",
            standby="102",
            workers=["201", "202"],
            proxy_job="203",
        )
    assert published == []


def test_signal_before_submit_never_spawns(monkeypatch: pytest.MonkeyPatch) -> None:
    M.STOP_EVENT.set()
    called = []
    monkeypatch.setattr(M.subprocess, "Popen", lambda *_args, **_kwargs: called.append(1))
    try:
        with pytest.raises(M.LaunchCancelled):
            M.bounded_submit(["/bin/false"], {})
    finally:
        M.STOP_EVENT.clear()
    assert called == []


def test_cleanup_queries_only_v12b_exact_job_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = []
    monkeypatch.setattr(M, "SUBMITTED_JOB_ID", None)
    monkeypatch.setattr(M, "COORDINATOR_RELEASED", False)
    monkeypatch.setattr(M, "name_job_ids", lambda name=M.JOB_NAME: names.append(name) or set())
    monkeypatch.setattr(M, "archive_failed_namespace", lambda: True)
    outcome = M.cleanup("token", [])
    assert outcome["all_terminal"] is True
    exact_names = [
        f"{M.DEPLOYMENT_ID}-coord",
        f"{M.DEPLOYMENT_ID}-ep",
        f"{M.DEPLOYMENT_ID}-proxy",
    ]
    assert names == exact_names * 3
    assert all("215851z" not in name and "231622z" not in name for name in names)
