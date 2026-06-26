# VENDORED from amaia-collab apps/sea/envs/envs/terminal_bench/evaluation.py (2026-06-15); only the two import lines repointed to local modules.
# Copyright (c) Meta Platforms, Inc. and affiliates.

import base64
import os
import json
import tarfile
import tempfile
from logging import getLogger
from pathlib import Path

from .models import TestResult
from .task_utils import is_v2_format

logger = getLogger()


# Markers that mean the ssh channel to the leased VM dropped (vs. a real task
# failure). When these appear during grading we can re-attach to the SAME
# container (work intact) and re-grade, instead of scoring a bogus 0.
_CONN_LOST_MARKERS = (
    "connectionreseterror",
    "connection reset",
    "connection lost",
    "broken pipe",
    "broken_pipe",
    "control socket",
    "connection closed",
    "session not initialized",
)


def _is_conn_lost(msg) -> bool:
    m = (msg or "").lower()
    return any(k in m for k in _CONN_LOST_MARKERS)


def _classify_grade_err(msg) -> str:
    """Tag a grading-stage infra failure so we always know WHAT broke."""
    m = (msg or "").lower()
    if _is_conn_lost(m):
        return "grade/conn_lost"
    if "upload" in m or "write chunk" in m or "extract" in m:
        return "grade/upload"
    if "timeout" in m:
        return "grade/timeout"
    return "grade/other"



def _chunked_upload(backend, data_b64: str, dest_path: str, timeout: float = 60.0) -> str | None:
    """Upload base64 data in chunks to avoid ARG_MAX. Returns error message or None."""
    chunk_size = 50000
    tmp_file = "/tmp/tb_upload.b64"
    backend.run_bash(f"rm -f {tmp_file}", timeout=10.0)
    for i in range(0, len(data_b64), chunk_size):
        chunk = data_b64[i:i + chunk_size]
        redirect = ">>" if i > 0 else ">"
        result = backend.run_bash(f"echo -n '{chunk}' {redirect} {tmp_file}", timeout=30.0)
        if result.get("exit_code", 1) != 0:
            return f"Failed to write chunk: {result.get('output', '')}"
    result = backend.run_bash(f"base64 -d {tmp_file} | tar -xf - -C {dest_path} && rm -f {tmp_file}", timeout=timeout)
    if result.get("exit_code", 1) != 0:
        return f"Failed to extract: {result.get('output', '')}"
    return None


INFRA_UV_BUNDLE = os.environ.get(
    "SEA_UV_BUNDLE",
    "/checkpoint/ram/tianhaowu/datasets/terminal_bench/infra_uv_bundle.tgz",
)


def _provision_infra_uv(backend) -> None:
    """Copy our isolated uv test-toolchain (uv binary + python3.13 + pytest
    cache) into the container's /opt/infra at TEST time (after solve, before
    test). test.sh's uvx then resolves entirely offline (UV_OFFLINE=1) with no
    GitHub/PyPI egress -> immune to the shared-IP 429 under concurrency.

    All of this lives in OUR infra code: the task image and tests/test.sh are
    never modified, and the solve phase never sees /opt/infra. Best-effort: if
    the bundle is missing or transfer fails, the test proceeds as before.
    """
    bundle = Path(INFRA_UV_BUNDLE)
    if not bundle.exists():
        logger.warning("infra uv bundle missing: %s (skipping provision)", bundle)
        return
    try:
        data = bundle.read_bytes()
        if hasattr(backend, "transfer_file"):
            backend.transfer_file(data, "/tmp/infra_uv.tgz")
        else:
            b64 = base64.b64encode(data).decode()
            backend.run_bash("rm -f /tmp/infra_uv.b64", timeout=10.0)
            for i in range(0, len(b64), 50000):
                rd = ">>" if i else ">"
                backend.run_bash(
                    f"echo -n '{b64[i:i + 50000]}' {rd} /tmp/infra_uv.b64", timeout=30.0
                )
            backend.run_bash(
                "base64 -d /tmp/infra_uv.b64 > /tmp/infra_uv.tgz && rm -f /tmp/infra_uv.b64",
                timeout=60.0,
            )
        r = backend.run_bash(
            "mkdir -p /opt/infra && tar -C /opt/infra -xzf /tmp/infra_uv.tgz && "
            "rm -f /tmp/infra_uv.tgz && /opt/infra/uv-bin/uvx --version",
            timeout=180.0,
        )
        logger.info("infra uv provisioned: %s", (r.get("output") or "").strip()[-80:])
    except Exception as e:
        logger.warning("infra uv provision failed (%s): test will proceed", e)


def _grade_once(
    backend,
    task_path: Path,
    parser_name: str = "pytest",
    test_timeout: float = 180.0,
    timeout_multiplier: float = 1.0,
    workdir: str = "/app",
) -> TestResult:
    """Run tests mirroring harbor's verifier flow:

    1. Upload task_path/tests/ contents to /tests/ in the container.
    2. chmod +x /tests/test.sh
    3. cd to workdir (harbor uses docker exec -w <workdir>, we share a session)
    4. Run /tests/test.sh with stdout/stderr captured to /logs/verifier/test-stdout.txt
    5. Read reward from /logs/verifier/reward.json or /logs/verifier/reward.txt
    """
    try:
        tests_dir = task_path / "tests"
        v2 = True

        # --- 1. Upload test files to /tests/ ---
        # Harbor: upload_dir(source_dir=task.paths.tests_dir, target_dir="/tests")
        with tempfile.NamedTemporaryFile(suffix=".tar") as tmp:
            with tarfile.open(tmp.name, "w") as tar:
                if tests_dir.exists() and tests_dir.is_dir():
                    if v2:
                        for item in tests_dir.iterdir():
                            tar.add(item, arcname=item.name)
                    else:
                        tar.add(tests_dir, arcname="tests")
            project_b64 = base64.b64encode(Path(tmp.name).read_bytes()).decode()

        if v2:
            test_mount = "/tests"
        else:
            test_mount = "/app"

        backend.run_bash(f"mkdir -p {test_mount} /logs/verifier", timeout=10.0)
        err = _chunked_upload(backend, project_b64, test_mount)
        if err:
            return TestResult(outcome="env_error", message=f"Failed to upload test files: {err}", test_output="", error_class=_classify_grade_err(err), error_detail=str(err)[:1000])

        # --- 2. chmod +x the test script ---
        # Harbor: chmod +x /tests/test.sh
        if v2:
            test_script = "/tests/test.sh"
        else:
            test_script = "/app/run-tests.sh"
        backend.run_bash(f"chmod +x {test_script}", timeout=10.0)

        # --- 3. Run the test script ---
        # Harbor: runs test_script with stdout redirected to /logs/verifier/test-stdout.txt
        # Harbor does NOT cd, does NOT set env vars, does NOT pre-install anything.
        # The test.sh itself handles all setup (installs uv, pytest, etc.)
        effective_timeout = test_timeout * timeout_multiplier
        if v2:
            # Provision our isolated uv toolchain (after solve, before test).
            _provision_infra_uv(backend)
            # Harbor runs test.sh via `docker exec -w <workdir>` which starts
            # a fresh process at the Dockerfile WORKDIR. We share a persistent
            # bash session, so cd there first.
            # Infra-isolated uv: point the task's test.sh at our pre-baked uv
            # toolchain (uv binary + python3.13 + pytest under /opt/infra) so its
            # GitHub fetch is non-fatal under concurrency (test.sh has no set -e).
            # Scoped to THIS test subshell only -> never leaks into the solve
            # phase or the image's own python. UV_CACHE_DIR / UV_PYTHON_INSTALL_DIR
            # are honored even by a freshly-installed uv; /opt/infra/uv-bin is a
            # PATH fallback if the curl install 429s. On an unbaked image the dirs
            # are simply absent -> uv falls back to a normal (empty) cache.
            infra_env = (
                "export INSTALLER_NO_MODIFY_PATH=1 "
                "UV_CACHE_DIR=/opt/infra/uv-cache UV_PYTHON_INSTALL_DIR=/opt/infra/uv-python; "
                "export PATH=/opt/infra/uv-bin:$PATH; "
            )
            run_cmd = f"cd {workdir} && ({infra_env}{test_script}) > /logs/verifier/test-stdout.txt 2>&1"
        else:
            run_cmd = (
                "export TEST_DIR=/app/tests && "
                "export PATH=$HOME/.local/bin:$PATH && "
                f"cd /app && bash {test_script} 2>&1"
            )
        result = backend.run_bash(run_cmd, timeout=effective_timeout)

        exit_code = result.get("exit_code", 1)
        timed_out = result.get("error_type") == "timeout"

        # Read the captured test output
        stdout_result = backend.run_bash("cat /logs/verifier/test-stdout.txt 2>/dev/null", timeout=30.0)
        test_output = stdout_result.get("output", "")

        logger.info(f"Test script exit_code={exit_code} timed_out={timed_out} output_len={len(test_output)}")
        if test_output:
            logger.debug(f"Test stdout (last 1000 chars): {test_output[-1000:]}")

        if timed_out:
            return TestResult(
                outcome="timeout",
                message=f"Test timeout after {effective_timeout}s",
                test_output=test_output,
                exit_code=exit_code,
            )

        # --- 4. Read reward ---
        # Harbor: checks reward.json first, then reward.txt.
        # Harbor parses reward.json with json.loads() -> dict[str, float|int]
        # Harbor parses reward.txt with float(path.read_text()) -> {"reward": float}
        reward_json_result = backend.run_bash("cat /logs/verifier/reward.json 2>/dev/null", timeout=30.0)
        reward_json_out = reward_json_result.get("output", "").strip()

        reward_txt_result = backend.run_bash("cat /logs/verifier/reward.txt 2>/dev/null", timeout=30.0)
        reward_txt_out = reward_txt_result.get("output", "").strip()

        logger.info(f"Reward files: reward.json={repr(reward_json_out)} reward.txt={repr(reward_txt_out)}")

        rewards = None
        if reward_json_out:
            try:
                rewards = json.loads(reward_json_out)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse reward.json: {e}, content={repr(reward_json_out)}")
        elif reward_txt_out:
            try:
                rewards = {"reward": float(reward_txt_out)}
            except ValueError as e:
                logger.warning(f"Failed to parse reward.txt: {e}, content={repr(reward_txt_out)}")

        if rewards is None:
            run_out = (result.get("output", "") or "")
            run_err = result.get("error_type")
            if run_err in ("broken_pipe", "other") or _is_conn_lost(run_out):
                logger.warning(
                    "No reward file AND session looked dropped during test run "
                    "(error_type=%s) -> env_error", run_err,
                )
                return TestResult(
                    outcome="env_error",
                    message=f"Connection lost during test run: {run_out[-400:]}",
                    test_output=test_output,
                    exit_code=exit_code,
                    error_class="grade/conn_lost",
                    error_detail=(run_out[-1000:] or run_err or "session error"),
                )
            logger.warning("No reward file found or parseable — treating as fail")
            return TestResult(
                outcome="fail",
                message=f"No reward file written by test script\n{test_output[-500:]}",
                test_output=test_output,
                exit_code=exit_code,
            )

        passed = rewards.get("reward", 0) >= 1.0
        logger.info(f"Reward parsed: {rewards} -> passed={passed}")

        return TestResult(
            outcome="pass" if passed else "fail",
            message="Tests passed" if passed else f"Tests failed\n{test_output[-500:]}",
            test_output=test_output,
            exit_code=exit_code,
        )

    except Exception as e:
        import traceback
        logger.error("run_terminal_bench_tests error for %s: %s\n%s",
                     task_path.name, e, traceback.format_exc())
        return TestResult(
            outcome="env_error",
            message=f"Error running tests: {e}\n{traceback.format_exc()}",
            test_output="",
            error_class=_classify_grade_err(str(e)),
            error_detail=f"{type(e).__name__}: {e}"[:1000],
        )


def run_terminal_bench_tests(
    backend,
    task_path: Path,
    parser_name: str = "pytest",
    test_timeout: float = 180.0,
    timeout_multiplier: float = 1.0,
    workdir: str = "/app",
) -> TestResult:
    """Grade the task, retrying on a *connection-loss* env_error.

    A dropped ssh channel (ConnectionResetError, broken pipe) during grading
    does NOT mean the work is lost: the leased VM and its container are still
    alive with the agent's full filesystem state. backend.restart_session()
    re-attaches a fresh bash session to the SAME container (no re-lease), so a
    re-grade is valid. We try up to VMVM_TB_GRADE_RETRIES times; any non-conn
    outcome (pass/fail/timeout, or an env_error we cannot recover from) returns
    immediately. EVERY infra error is logged with its actual cause + class."""
    max_attempts = max(1, int(os.environ.get("VMVM_TB_GRADE_RETRIES", "3")))
    events: list = []
    last = None
    for attempt in range(max_attempts):
        res = _grade_once(backend, task_path, parser_name, test_timeout,
                          timeout_multiplier, workdir)
        last = res
        if res.outcome != "env_error":
            res.infra_events = events or None  # may be [] -> None if first try clean
            return res
        # Always record what the infra error actually was (log + structured).
        logger.error(
            "GRADE infra-error for %s (attempt %d/%d) class=%s: %s",
            task_path.name, attempt + 1, max_attempts,
            res.error_class, (res.error_detail or res.message or "")[:500],
        )
        events.append({"phase": "grade", "type": res.error_class or "env_error",
                       "attempt": attempt + 1,
                       "detail": (res.error_detail or res.message or "")[:300]})
        if not (_is_conn_lost(res.message) or res.error_class == "grade/conn_lost"):
            res.infra_events = events
            return res  # non-transient infra error -> do not retry
        if attempt + 1 >= max_attempts:
            res.infra_events = events
            return res
        ok = False
        if hasattr(backend, "restart_session"):
            try:
                ok = backend.restart_session()
            except Exception as e:
                logger.warning("grade retry: restart_session raised: %s", e)
                ok = False
        events.append({"phase": "grade", "type": "reconnect", "attempt": attempt + 1,
                       "ok": bool(ok)})
        logger.warning(
            "GRADE conn-lost for %s -> restart_session(same box) ok=%s; %s",
            task_path.name, ok,
            "retrying re-grade" if ok else "box gone, giving up",
        )
        if not ok:
            res.infra_events = events
            return res  # box genuinely gone -> nothing to grade
    if last is not None:
        last.infra_events = events
    return last
