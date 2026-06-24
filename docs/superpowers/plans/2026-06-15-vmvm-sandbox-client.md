# VMVM Sandbox Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let PRIME-RL run rollouts inside VMs leased from the internal VMVM pool via `vacli`, by providing a `prime_sandboxes`-shaped `VMVMSandboxClient` and a `vf.SandboxEnv` subclass that uses it.

**Architecture:** Classic `SandboxEnv` bash-tool flow (model runs outside the VM; only commands flow in, so no interception egress). We vendor a trimmed copy of amaia-collab's server-backed vacli backend, wrap it in an async `VMVMSandboxClient`, and inject that client into a `VMVMSandboxEnv(vf.SandboxEnv)`. Packaged as an importable `vmvm_swe` module so `vf.load_environment("vmvm-swe")` finds it. No PRIME-RL core changes.

**Tech Stack:** Python 3.12, `uv`, `pytest`, `verifiers`, `prime-sandboxes` (types only), vendored vacli/SSH/AsyncSession code. Runs on **fair-sc** (`~/prime-rl`, branch `vmvm-sandbox`).

**Spec:** `docs/superpowers/specs/2026-06-15-vmvm-sandbox-client-design.md`

**Conventions for every command below:** run on fair-sc from `~/prime-rl` on branch `vmvm-sandbox`. Vendoring source repo is `~/amaia-collab`.

---

## File Structure

```
environments/vmvm_swe/
  pyproject.toml                 # installable; top-level module `vmvm_swe`
  vmvm_swe/
    __init__.py                  # re-exports load_environment
    _vacli/
      __init__.py
      types.py                   # vendored: BackendInitError, BashResult, SessionOutput
      session.py                 # vendored verbatim: AsyncSession
      backend.py                 # vendored + trimmed: VacliVMVMConfig, VacliVMVMBackend
    client.py                    # VMVMSandboxClient (authored)
    env.py                       # VMVMSandboxEnv + load_environment + reward (authored)
  tests/
    test_client.py               # unit, fake backend
    test_env.py                  # unit, fake client
    test_smoke_live.py           # live, gated by env var
examples/vmvm_swe/rl.toml        # references id = "vmvm-swe"
```

---

## Task 0: Scaffold the package and make it importable

**Files:**
- Create: `environments/vmvm_swe/pyproject.toml`
- Create: `environments/vmvm_swe/vmvm_swe/__init__.py`
- Create: `environments/vmvm_swe/vmvm_swe/_vacli/__init__.py`
- Test: `environments/vmvm_swe/tests/test_import.py`

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "vmvm-swe"
version = "0.1.0"
description = "PRIME-RL environment running rollouts on the VMVM pool via vacli"
requires-python = ">=3.12"
dependencies = [
    "verifiers",
    "prime-sandboxes",
    "datasets",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["vmvm_swe"]
```

- [ ] **Step 2: Write the package __init__ files**

`environments/vmvm_swe/vmvm_swe/__init__.py`:
```python
from .env import load_environment

__all__ = ["load_environment"]
```

`environments/vmvm_swe/vmvm_swe/_vacli/__init__.py`:
```python
```
(empty file)

- [ ] **Step 3: Write the failing import test**

`environments/vmvm_swe/tests/test_import.py`:
```python
def test_module_name_resolves():
    # verifiers maps env id "vmvm-swe" -> module "vmvm_swe"
    import importlib
    mod = importlib.import_module("vmvm_swe")
    assert hasattr(mod, "load_environment")
```

- [ ] **Step 4: Run the test — expect FAIL (module not yet installed / env.py missing)**

Run: `cd ~/prime-rl && uv run pytest environments/vmvm_swe/tests/test_import.py -v`
Expected: FAIL (ModuleNotFoundError: vmvm_swe, or ImportError from missing env.py).

- [ ] **Step 5: Defer** — this test passes only after Task 5 creates `env.py`. Leave it failing for now; do NOT stub env.py. Proceed to Task 1.

- [ ] **Step 6: Commit**

```bash
cd ~/prime-rl && git add environments/vmvm_swe/pyproject.toml environments/vmvm_swe/vmvm_swe/__init__.py environments/vmvm_swe/vmvm_swe/_vacli/__init__.py environments/vmvm_swe/tests/test_import.py && git commit -m "scaffold vmvm_swe env package"
```

---

## Task 1: Vendor AsyncSession (verbatim)

`apps/rl/utils/remote/session.py` is standalone (stdlib-only) and defines `AsyncSession` + `SessionOutput`. Copy it verbatim.

**Files:**
- Create: `environments/vmvm_swe/vmvm_swe/_vacli/session.py`

- [ ] **Step 1: Copy the file**

```bash
cp ~/amaia-collab/apps/rl/utils/remote/session.py ~/prime-rl/environments/vmvm_swe/vmvm_swe/_vacli/session.py
```

- [ ] **Step 2: Prepend a provenance header**

Add these two lines at the very top of `environments/vmvm_swe/vmvm_swe/_vacli/session.py`:
```python
# VENDORED from amaia-collab apps/rl/utils/remote/session.py (snapshot 2026-06-15).
# Do not edit; re-vendor from source if upstream changes.
```

- [ ] **Step 3: Verify it imports with stdlib only**

Run: `cd ~/prime-rl && uv run python -c "from vmvm_swe._vacli.session import AsyncSession, SessionOutput; print('ok')"`
Expected: prints `ok` (after editable install in Task 4 Step 1; if not yet installed, run `cd ~/prime-rl && uv pip install -e environments/vmvm_swe` first).
Note: if this errors with ModuleNotFoundError for any `apps.*` import, the file was NOT standalone — STOP and report; the vendoring assumption is wrong.

- [ ] **Step 4: Commit**

```bash
cd ~/prime-rl && git add environments/vmvm_swe/vmvm_swe/_vacli/session.py && git commit -m "vendor AsyncSession from amaia-collab"
```

---

## Task 2: Vendor BackendInitError + BashResult types

`backend.py` imports `BackendInitError, BashResult` from `apps.rl.utils.des_helper`. `BashResult` is a TypedDict extending `SessionOutput`. Provide a tiny local module instead of vendoring all of `des_helper`.

**Files:**
- Create: `environments/vmvm_swe/vmvm_swe/_vacli/types.py`

- [ ] **Step 1: Confirm the upstream BashResult definition**

Run: `grep -nE "class BashResult|class BackendInitError" ~/amaia-collab/apps/rl/utils/des_helper.py`
Expected: shows `class BashResult(SessionOutput)` and a `BackendInitError` definition. Read the `BashResult` body to confirm its extra fields.

- [ ] **Step 2: Write types.py**

`environments/vmvm_swe/vmvm_swe/_vacli/types.py`:
```python
# Minimal local copy of the types backend.py needs from amaia-collab's
# apps/rl/utils/des_helper (snapshot 2026-06-15).
from .session import SessionOutput


class BackendInitError(Exception):
    """Raised when a sandbox/container cannot be created or started."""


class BashResult(SessionOutput):
    # SessionOutput already has: status, output, error_type.
    exit_code: int
```

- [ ] **Step 3: Verify**

Run: `cd ~/prime-rl && uv run python -c "from vmvm_swe._vacli.types import BackendInitError, BashResult; print('ok')"`
Expected: `ok`.
Note: if Step 1 showed `BashResult` carries fields beyond `exit_code`, add them here to match.

- [ ] **Step 4: Commit**

```bash
cd ~/prime-rl && git add environments/vmvm_swe/vmvm_swe/_vacli/types.py && git commit -m "vendor BackendInitError/BashResult types"
```

---

## Task 3: Vendor + trim the vacli backend

Copy `vacli_backend.py`, repoint its imports to the vendored modules, and strip the amaia tool/plugin coupling (the env does not need it — verifiers provides the bash tool).

**Files:**
- Create: `environments/vmvm_swe/vmvm_swe/_vacli/backend.py`

- [ ] **Step 1: Copy the file**

```bash
cp ~/amaia-collab/apps/rl/swerl/vacli_backend.py ~/prime-rl/environments/vmvm_swe/vmvm_swe/_vacli/backend.py
```

- [ ] **Step 2: Repoint the three amaia imports**

In `environments/vmvm_swe/vmvm_swe/_vacli/backend.py`, replace:
```python
from apps.rl.utils.des_helper import BackendInitError, BashResult
from apps.rl.utils.remote.session import AsyncSession, SessionOutput
from apps.rl.swerl.tools import (
    ToolBackend,
    ToolType,
    make_python_plugins_from_dir,
)
```
with:
```python
from .types import BackendInitError, BashResult
from .session import AsyncSession, SessionOutput
```

- [ ] **Step 3: Strip the tool/plugin coupling from VacliVMVMConfig**

In `VacliVMVMConfig`, delete these four fields entirely:
```python
    plugin_root: str
    bind_target: str
    tools: dict[str, ToolType]
    plugin_names: list[str]
```
Keep all other fields (`image_url`, `work_dir`, `session_timeout`, `start_script`, `entrypoint_script`, `fallback_image_url`, `tenant_id`, `lease_ttl`, `tunnel_ready_timeout`, `sshd_ready_timeout`, `client_id`, `max_session_buffer_size`, `subprocess_mod`).

- [ ] **Step 4: Strip the tool/plugin coupling from VacliVMVMBackend**

In `class VacliVMVMBackend`:
1. Change the class declaration `class VacliVMVMBackend(ToolBackend):` to `class VacliVMVMBackend:`.
2. Delete the `tools` property:
```python
    @property
    def tools(self) -> dict[str, ToolType]:
        return self._tools
```
3. In `__init__`, delete the `_tools` construction block:
```python
        self._tools: dict[str, ToolType] = {
            **config.tools,
            **make_python_plugins_from_dir(
                config.plugin_root,
                config.bind_target,
                plugin_names=config.plugin_names,
            ),
        }
```

- [ ] **Step 5: Delete the NoServer variant and any other tool-coupled classes**

Delete `class VacliVMVMBackend_NoServer` and its config `class VacliVMVMNoServerConfig` entirely (they also reference `tools`/`ToolType`/`ToolBackend` and we do not use them). Keep `VacliLease`, `VacliSession`, `VacliVMVMConfig`, `VacliVMVMBackend`, `_validate_container_id`, and all module-level helpers/constants.

- [ ] **Step 6: Verify the trim — import must be clean**

Run: `cd ~/prime-rl && uv run python -c "from vmvm_swe._vacli.backend import VacliVMVMBackend, VacliVMVMConfig; print('ok')"`
Expected: `ok`.
If it raises `NameError`/`ImportError` mentioning `ToolType`, `ToolBackend`, or `make_python_plugins_from_dir`, find and remove that residual reference (it is dead code from the trimmed surface), then re-run. Do not add the amaia import back.

- [ ] **Step 7: Commit**

```bash
cd ~/prime-rl && git add environments/vmvm_swe/vmvm_swe/_vacli/backend.py && git commit -m "vendor + trim vacli backend (drop tool/plugin coupling)"
```

---

## Task 4: VMVMSandboxClient (TDD with a fake backend)

The client maps the `prime_sandboxes` client surface that `SandboxEnv` calls onto the sync vacli backend, bridging to async via threads.

**Files:**
- Create: `environments/vmvm_swe/vmvm_swe/client.py`
- Test: `environments/vmvm_swe/tests/test_client.py`

- [ ] **Step 1: Install the package editable (once)**

```bash
cd ~/prime-rl && uv pip install -e environments/vmvm_swe
```
Expected: installs `vmvm-swe` (and `datasets` if missing).

- [ ] **Step 2: Write the failing tests**

`environments/vmvm_swe/tests/test_client.py`:
```python
import asyncio
import types

import pytest

import vmvm_swe.client as client_mod
from vmvm_swe.client import VMVMSandboxClient


class FakeBackend:
    """Stand-in for VacliVMVMBackend: records calls, returns BashResult dicts."""
    instances = []

    def __init__(self, config):
        self.config = config
        self.destroyed = False
        self.calls = []
        FakeBackend.instances.append(self)

    def run_bash(self, command, timeout=60.0):
        self.calls.append((command, timeout))
        if command == "TIMEOUT":
            return {"status": "error", "output": "", "error_type": "timeout", "exit_code": -1}
        return {"status": "success", "output": f"ran:{command}", "error_type": "none", "exit_code": 0}

    def destroy(self):
        self.destroyed = True


@pytest.fixture(autouse=True)
def patch_backend(monkeypatch):
    FakeBackend.instances = []
    monkeypatch.setattr(client_mod, "VacliVMVMBackend", FakeBackend)
    monkeypatch.setattr(client_mod, "VacliVMVMConfig", lambda **kw: types.SimpleNamespace(**kw))


def _req(image="img:tag"):
    return types.SimpleNamespace(docker_image=image)


def test_create_returns_handle_with_id():
    c = VMVMSandboxClient(tenant_id="t")
    h = asyncio.run(c.create(_req("python:3.11-slim")))
    assert h.id.startswith("vmvm-")
    assert FakeBackend.instances[-1].config.image_url == "python:3.11-slim"


def test_execute_command_maps_stdout():
    c = VMVMSandboxClient(tenant_id="t")
    h = asyncio.run(c.create(_req()))
    res = asyncio.run(c.execute_command(h.id, "echo hi"))
    assert res.stdout == "ran:echo hi"
    assert res.stderr == ""


def test_execute_command_prefixes_working_dir():
    c = VMVMSandboxClient(tenant_id="t")
    h = asyncio.run(c.create(_req()))
    asyncio.run(c.execute_command(h.id, "ls", working_dir="/app"))
    assert FakeBackend.instances[-1].calls[-1][0] == "cd /app && ls"


def test_timeout_raises_command_timeout_error():
    from prime_sandboxes import CommandTimeoutError
    c = VMVMSandboxClient(tenant_id="t")
    h = asyncio.run(c.create(_req()))
    with pytest.raises(CommandTimeoutError):
        asyncio.run(c.execute_command(h.id, "TIMEOUT", timeout=5))


def test_delete_destroys_backend():
    c = VMVMSandboxClient(tenant_id="t")
    h = asyncio.run(c.create(_req()))
    backend = FakeBackend.instances[-1]
    asyncio.run(c.delete(h.id))
    assert backend.destroyed is True
    assert h.id not in c._backends


def test_teardown_destroys_all():
    c = VMVMSandboxClient(tenant_id="t")
    asyncio.run(c.create(_req()))
    asyncio.run(c.create(_req()))
    c.teardown()
    assert all(b.destroyed for b in FakeBackend.instances)
```

- [ ] **Step 3: Run the tests — expect FAIL (client.py missing)**

Run: `cd ~/prime-rl && uv run pytest environments/vmvm_swe/tests/test_client.py -v`
Expected: collection error / ImportError: cannot import VMVMSandboxClient.

- [ ] **Step 4: Implement client.py**

`environments/vmvm_swe/vmvm_swe/client.py`:
```python
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

from prime_sandboxes import CommandTimeoutError

from ._vacli.backend import VacliVMVMBackend, VacliVMVMConfig

logger = logging.getLogger(__name__)

# error_type values (from SessionOutput) that mean the command timed out.
_TIMEOUT_ERROR_TYPES = {"timeout"}


class _Handle:
    """Minimal stand-in for prime_sandboxes' Sandbox object: only `.id` is read."""

    def __init__(self, sandbox_id: str) -> None:
        self.id = sandbox_id


class VMVMSandboxClient:
    """Async, prime_sandboxes-shaped client backed by one vacli-leased VM per sandbox.

    Implements only the methods verifiers' SandboxEnv calls:
    create / wait_for_creation / execute_command / delete / bulk_delete / teardown.
    The vacli backend is synchronous; every call is bridged via asyncio.to_thread.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        work_dir: str = "/",
        session_timeout: float = 60.0,
        lease_ttl: str = "500s",
        fallback_image_url: str | None = None,
        start_script: str = "",
        client_id: str = "cwm_rl",
    ) -> None:
        self._tenant_id = tenant_id
        self._work_dir = work_dir
        self._session_timeout = session_timeout
        self._lease_ttl = lease_ttl
        self._fallback_image_url = fallback_image_url
        self._start_script = start_script
        self._client_id = client_id
        self._backends: dict[str, VacliVMVMBackend] = {}
        self._counter = 0

    async def create(self, request: Any) -> _Handle:
        cfg = VacliVMVMConfig(
            image_url=request.docker_image,
            work_dir=self._work_dir,
            session_timeout=self._session_timeout,
            start_script=self._start_script,
            tenant_id=self._tenant_id,
            lease_ttl=self._lease_ttl,
            fallback_image_url=self._fallback_image_url,
            client_id=self._client_id,
        )
        # VacliVMVMBackend.__init__ leases the VM, opens the tunnel, starts the
        # container, and starts the persistent bash session — all blocking.
        backend = await asyncio.to_thread(VacliVMVMBackend, cfg)
        self._counter += 1
        sandbox_id = f"vmvm-{self._counter}"
        self._backends[sandbox_id] = backend
        logger.debug("created VMVM sandbox %s (image=%s)", sandbox_id, request.docker_image)
        return _Handle(sandbox_id)

    async def wait_for_creation(self, sandbox_id: str) -> None:
        # create() already blocked until everything was ready.
        if sandbox_id not in self._backends:
            raise KeyError(f"unknown sandbox {sandbox_id}")

    async def execute_command(
        self,
        sandbox_id: str,
        command: str,
        working_dir: str | None = None,
        timeout: float = 60.0,
    ) -> SimpleNamespace:
        backend = self._backends[sandbox_id]
        cmd = command if working_dir is None else f"cd {working_dir} && {command}"
        result = await asyncio.to_thread(backend.run_bash, cmd, timeout)
        if result["error_type"] in _TIMEOUT_ERROR_TYPES:
            raise CommandTimeoutError(sandbox_id, command, timeout)
        return SimpleNamespace(stdout=result["output"], stderr="")

    async def delete(self, sandbox_id: str) -> None:
        backend = self._backends.pop(sandbox_id, None)
        if backend is not None:
            await asyncio.to_thread(backend.destroy)

    async def bulk_delete(self, sandbox_ids) -> None:
        for sid in list(sandbox_ids):
            await self.delete(sid)

    def teardown(self, wait: bool = True) -> None:
        for backend in list(self._backends.values()):
            try:
                backend.destroy()
            except Exception:
                logger.warning("failed to destroy backend during teardown", exc_info=True)
        self._backends.clear()
```

- [ ] **Step 5: Run the tests — expect PASS**

Run: `cd ~/prime-rl && uv run pytest environments/vmvm_swe/tests/test_client.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
cd ~/prime-rl && git add environments/vmvm_swe/vmvm_swe/client.py environments/vmvm_swe/tests/test_client.py && git commit -m "feat: VMVMSandboxClient (vacli-backed, async)"
```

---

## Task 5: VMVMSandboxEnv + reward + load_environment (TDD with a fake client)

Subclass `SandboxEnv`, inject `VMVMSandboxClient`, pick the per-task image, run the task tests in `post_rollout`, and expose `load_environment`.

**Files:**
- Create: `environments/vmvm_swe/vmvm_swe/env.py`
- Test: `environments/vmvm_swe/tests/test_env.py`

- [ ] **Step 1: Write the failing tests**

`environments/vmvm_swe/tests/test_env.py`:
```python
import asyncio
import json
import types

import pytest

import vmvm_swe.env as env_mod


class FakeClient:
    def __init__(self, **kw):
        self.kw = kw
        self.commands = []
        self.deleted = []

    async def create(self, request):
        return types.SimpleNamespace(id="vmvm-1")

    async def wait_for_creation(self, sandbox_id):
        return None

    async def execute_command(self, sandbox_id, command, working_dir=None, timeout=60.0):
        self.commands.append(command)
        ok = "__PASSED_SENTINEL__" if "RUN_TESTS_OK" in command else ""
        return types.SimpleNamespace(stdout=ok, stderr="")

    async def delete(self, sandbox_id):
        self.deleted.append(sandbox_id)

    async def bulk_delete(self, ids):
        self.deleted.extend(ids)

    def teardown(self, wait=True):
        pass


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(env_mod, "VMVMSandboxClient", FakeClient)
    e = env_mod.VMVMSandboxEnv(
        tenant_id="t",
        default_image="python:3.11-slim",
        dataset=env_mod._rows_to_dataset(
            [{"question": "q", "answer": "", "info": {"image": "img:1", "test_cmd": "pytest"}}]
        ),
        rubric=env_mod._build_rubric(),
        max_turns=2,
    )
    return e


def test_get_sandbox_request_uses_task_image(env):
    state = {"info": {"image": "img:1"}}
    req = env.get_sandbox_request(state)
    assert req.docker_image == "img:1"


def test_get_sandbox_request_falls_back_to_default(env):
    state = {"info": {}}
    req = env.get_sandbox_request(state)
    assert req.docker_image == "python:3.11-slim"


def test_post_rollout_runs_tests_and_caches_pass(env):
    state = {"sandbox_id": "vmvm-1", "info": {"test_cmd": "RUN_TESTS_OK"}}
    asyncio.run(env.post_rollout(state))
    assert state["test_passed"] == 1.0
    # the test command was wrapped with the success sentinel
    assert any("__PASSED_SENTINEL__" in c for c in env.sandbox_client.commands)


def test_post_rollout_caches_fail_when_no_sentinel(env):
    state = {"sandbox_id": "vmvm-1", "info": {"test_cmd": "false"}}
    asyncio.run(env.post_rollout(state))
    assert state["test_passed"] == 0.0


def test_reward_reads_cached_flag():
    rubric = env_mod._build_rubric()
    func = rubric.funcs[0] if hasattr(rubric, "funcs") else env_mod.test_passed_reward
    assert asyncio.run(env_mod.test_passed_reward(state={"test_passed": 1.0})) == 1.0
    assert asyncio.run(env_mod.test_passed_reward(state={})) == 0.0


def test_load_environment_smoke(monkeypatch, tmp_path):
    monkeypatch.setattr(env_mod, "VMVMSandboxClient", FakeClient)
    ds = tmp_path / "tasks.jsonl"
    ds.write_text(json.dumps({"question": "q", "answer": "", "info": {"image": "img:1", "test_cmd": "pytest"}}) + "\n")
    e = env_mod.load_environment(dataset_path=str(ds), tenant_id="t")
    assert isinstance(e, env_mod.VMVMSandboxEnv)
```

- [ ] **Step 2: Run the tests — expect FAIL (env.py missing)**

Run: `cd ~/prime-rl && uv run pytest environments/vmvm_swe/tests/test_env.py -v`
Expected: ImportError: cannot import vmvm_swe.env.

- [ ] **Step 3: Implement env.py**

`environments/vmvm_swe/vmvm_swe/env.py`:
```python
from __future__ import annotations

import json
import logging
from pathlib import Path

import verifiers as vf
from datasets import Dataset
from prime_sandboxes import CreateSandboxRequest
from verifiers.envs.sandbox_env import SandboxEnv

from .client import VMVMSandboxClient

logger = logging.getLogger(__name__)

# Marker echoed only when the task's test command exits 0.
_PASS_SENTINEL = "__PASSED_SENTINEL__"


async def test_passed_reward(state, **kwargs) -> float:
    """Reward = whether the task's tests passed (computed in post_rollout)."""
    return float(state.get("test_passed", 0.0))


def _build_rubric() -> vf.Rubric:
    return vf.Rubric(funcs=[test_passed_reward], weights=[1.0])


def _rows_to_dataset(rows: list[dict]) -> Dataset:
    return Dataset.from_list(rows)


def _load_dataset(dataset_path: str) -> Dataset:
    """Read a JSONL file of rows: {question, answer, info:{image, test_cmd}}."""
    if not dataset_path:
        # Minimal placeholder task so the env is constructible without data.
        return _rows_to_dataset(
            [{"question": "noop", "answer": "", "info": {"test_cmd": "true"}}]
        )
    rows = []
    with open(dataset_path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return _rows_to_dataset(rows)


class VMVMSandboxEnv(SandboxEnv):
    """SandboxEnv whose per-rollout sandbox is a vacli-leased VMVM VM."""

    def __init__(
        self,
        *,
        tenant_id: str,
        default_image: str = "python:3.11-slim",
        work_dir: str = "/",
        session_timeout: float = 60.0,
        lease_ttl: str = "500s",
        timeout_per_command_seconds: int = 60,
        **kwargs,
    ) -> None:
        super().__init__(
            docker_image=default_image,
            timeout_per_command_seconds=timeout_per_command_seconds,
            **kwargs,
        )
        # Replace the prime_sandboxes client with the vacli-backed one.
        self.sandbox_client = VMVMSandboxClient(
            tenant_id=tenant_id,
            work_dir=work_dir,
            session_timeout=session_timeout,
            lease_ttl=lease_ttl,
        )

    def get_sandbox_request(self, state) -> CreateSandboxRequest:
        request = self.sandbox_request.model_copy()
        image = (state.get("info") or {}).get("image")
        if image:
            request.docker_image = image
        return request

    async def post_rollout(self, state) -> None:
        """Run the task's tests in the VM before it is destroyed; cache pass/fail."""
        info = state.get("info") or {}
        test_cmd = info.get("test_cmd")
        sandbox_id = state.get("sandbox_id")
        if not test_cmd or sandbox_id is None:
            state["test_passed"] = 0.0
            return
        wrapped = f"{test_cmd} && echo {_PASS_SENTINEL}"
        try:
            result = await self.sandbox_client.execute_command(
                sandbox_id, wrapped, working_dir=None,
                timeout=self.timeout_per_command_seconds,
            )
            state["test_passed"] = 1.0 if _PASS_SENTINEL in result.stdout else 0.0
        except Exception:
            logger.warning("test command failed in sandbox %s", sandbox_id, exc_info=True)
            state["test_passed"] = 0.0

    @vf.teardown
    async def teardown_sandboxes(self):  # override: never call prime's hosted API
        if not self.active_sandboxes:
            return
        await self.sandbox_client.bulk_delete(list(self.active_sandboxes))
        self.active_sandboxes.clear()


def load_environment(
    dataset_path: str = "",
    tenant_id: str = "async_2347641",
    default_image: str = "python:3.11-slim",
    work_dir: str = "/",
    session_timeout: float = 60.0,
    lease_ttl: str = "500s",
    timeout_per_command_seconds: int = 60,
    max_turns: int = 30,
    **kwargs,
) -> vf.Environment:
    dataset = _load_dataset(dataset_path)
    return VMVMSandboxEnv(
        tenant_id=tenant_id,
        default_image=default_image,
        work_dir=work_dir,
        session_timeout=session_timeout,
        lease_ttl=lease_ttl,
        timeout_per_command_seconds=timeout_per_command_seconds,
        dataset=dataset,
        rubric=_build_rubric(),
        max_turns=max_turns,
        **kwargs,
    )
```

- [ ] **Step 4: Run the env tests — expect PASS**

Run: `cd ~/prime-rl && uv run pytest environments/vmvm_swe/tests/test_env.py -v`
Expected: all passed.
If `super().__init__` errors because `SandboxEnv` registers the base `teardown_sandboxes` in addition to our override, inspect how `@vf.teardown` collects handlers (`verifiers/envs/sandbox_env.py` + the decorator). If both register, drop our `@vf.teardown` decorator and instead override the base method body (same name, no decorator) so only the inherited registration runs but resolves to our implementation. Re-run.

- [ ] **Step 5: Run the import test from Task 0 — now expect PASS**

Run: `cd ~/prime-rl && uv run pytest environments/vmvm_swe/tests/test_import.py -v`
Expected: passed (module `vmvm_swe` now exposes `load_environment`).

- [ ] **Step 6: Commit**

```bash
cd ~/prime-rl && git add environments/vmvm_swe/vmvm_swe/env.py environments/vmvm_swe/tests/test_env.py && git commit -m "feat: VMVMSandboxEnv + task-test reward + load_environment"
```

---

## Task 6: PRIME-RL example TOML

**Files:**
- Create: `examples/vmvm_swe/rl.toml`

- [ ] **Step 1: Write the example config**

`examples/vmvm_swe/rl.toml` (debug-scale; adjust model/deployment to your cluster):
```toml
seq_len = 32768

[model]
name = "Qwen/Qwen3-4B-Instruct-2507"

[orchestrator]
batch_size = 8

[[orchestrator.train.env]]
id = "vmvm-swe"
name = "vmvm-swe"
args = { dataset_path = "/shared/vmvm_swe/tasks.jsonl", tenant_id = "async_2347641", default_image = "python:3.11-slim", timeout_per_command_seconds = 60, max_turns = 30 }
```

- [ ] **Step 2: Validate the TOML parses and the env id resolves**

Run: `cd ~/prime-rl && uv run python -c "import tomllib; tomllib.load(open('examples/vmvm_swe/rl.toml','rb')); from verifiers.utils.env_utils import env_module_name; assert env_module_name('vmvm-swe') == 'vmvm_swe'; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
cd ~/prime-rl && git add examples/vmvm_swe/rl.toml && git commit -m "example: vmvm-swe rl.toml"
```

---

## Task 7: Live smoke against the VMVM pool (gated)

This is the only test that leases a real VM. It is gated by an env var so CI/offline runs skip it. Run it manually on fair-sc where `vacli` is available.

**Files:**
- Create: `environments/vmvm_swe/tests/test_smoke_live.py`

- [ ] **Step 1: Write the gated live test**

`environments/vmvm_swe/tests/test_smoke_live.py`:
```python
import asyncio
import os
import types

import pytest

from vmvm_swe.client import VMVMSandboxClient

pytestmark = pytest.mark.skipif(
    os.environ.get("VMVM_LIVE") != "1",
    reason="set VMVM_LIVE=1 to run the live vacli smoke test",
)


def test_live_create_exec_destroy():
    tenant = os.environ.get("VMVM_TENANT", "async_2347641")
    image = os.environ.get("VMVM_IMAGE", "python:3.11-slim")
    c = VMVMSandboxClient(tenant_id=tenant, session_timeout=120.0)

    async def run():
        h = await c.create(types.SimpleNamespace(docker_image=image))
        try:
            await c.wait_for_creation(h.id)
            res = await c.execute_command(h.id, "echo hello-vmvm", timeout=60)
            assert "hello-vmvm" in res.stdout
        finally:
            await c.delete(h.id)

    asyncio.run(run())
```

- [ ] **Step 2: Run it live (manual)**

Run: `cd ~/prime-rl && VMVM_LIVE=1 uv run pytest environments/vmvm_swe/tests/test_smoke_live.py -v -s`
Expected: PASS — a VM leases, `echo hello-vmvm` round-trips, the VM is released.
This validates the vendored vacli path end-to-end (lease -> tunnel -> sshd -> container -> bash -> destroy).
If it fails, the failure is in the vendored backend bring-up, not the authored client — read the vacli lease log path printed in the backend's debug logs.

- [ ] **Step 3: Commit**

```bash
cd ~/prime-rl && git add environments/vmvm_swe/tests/test_smoke_live.py && git commit -m "test: live vacli smoke (gated by VMVM_LIVE)"
```

- [ ] **Step 4: Run the full offline suite**

Run: `cd ~/prime-rl && uv run pytest environments/vmvm_swe/tests -v -m "not skip"`
Expected: all non-live tests pass (live test skipped without VMVM_LIVE).

---

## Done criteria

- `uv run pytest environments/vmvm_swe/tests` green (offline).
- `VMVM_LIVE=1 uv run pytest .../test_smoke_live.py` green on fair-sc.
- `examples/vmvm_swe/rl.toml` references `id = "vmvm-swe"` and resolves to the installed module.
- Next milestone (separate plan): run the PRIME-RL orchestrator against a debug inference server using this env and confirm trajectories + rewards populate (spec §10 P3/P4).
