# Design: VMVM Sandbox Client for PRIME-RL

- **Date:** 2026-06-15
- **Status:** Draft (awaiting review)
- **Author:** thwu1
- **Repo:** thwu1/prime-rl (fork)

## 1. Goal

Train an agent in PRIME-RL where every rollout executes inside a VM leased from
the internal **VMVM pool via `vacli`**, instead of Prime Intellect's hosted
sandboxes (`prime_sandboxes`). Reuse the proven vacli lease/exec machinery from
`amaia-collab`'s SWE-RL backend.

## 2. Key constraint: avoid the interception network path

PRIME-RL's shipped SWE/agentic envs (`mini-swe-agent-plus`, `terminus-harbor`)
run the agent *inside* the sandbox and **intercept** its LLM calls via a proxy
the VM must dial back to. Over vacli's x2p tunnel the leased VM cannot reliably
reach back to the orchestrator (the known non-login-shell egress problem), so
the interception path is **out of scope**.

Instead we use the **classic `SandboxEnv` bash-tool flow**: the policy model runs
outside the VM (on PRIME-RL's vLLM fleet); verifiers parses the model's tool
calls and only sends bash commands *into* the VM. Every connection is
orchestrator/env -> VM (inbound to the VM over the existing tunnel). The VM never
dials out to the orchestrator. Grading also runs inbound (`execute_command` of
the test command).

## 3. Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Integration style | **Option 1a**: subclass `vf.SandboxEnv`, swap `self.sandbox_client` for a vacli-backed client. Reuse the inherited rollout/tool/cleanup lifecycle. |
| 2 | vacli dependency | **Vendor** a minimal copy of the vacli lease/exec code into the env package. No runtime dependency on `amaia-collab`. |
| 3 | vacli variant | **Server-backed `VacliVMVMBackend`** (persistent bash session via the in-container remote server). |
| 4 | Reward | **Run the task's tests** via `execute_command` after the agent submits; binary/score. |
| 5 | Package home | `thwu1/prime-rl/environments/vmvm_swe/` (self-contained, importable module `vmvm_swe`). |

## 4. How PRIME-RL loads this

`vf.load_environment("vmvm-swe", **args)` resolves the id by
`importlib.import_module("vmvm_swe")` and calls the module's
`load_environment(**args)`. Therefore the deliverable is an installable Python
package whose top-level module is `vmvm_swe` exposing `load_environment`.
**No changes to PRIME-RL core are required** — only an example TOML referencing
`id = "vmvm-swe"`.

## 5. Architecture

```
PRIME-RL orchestrator
  └─ vf.load_environment("vmvm-swe", **args)
       └─ VMVMSandboxEnv(vf.SandboxEnv)
            self.sandbox_client = VMVMSandboxClient(...)      # the swap
            rubric = Rubric([run_task_tests_reward])
  inherited rollout loop (unchanged):
    setup_state  -> client.create(req) -> client.wait_for_creation(id)
    bash tool    -> client.execute_command(id, cmd, working_dir, timeout)
    cleanup      -> client.delete(id)

VMVMSandboxClient (async; threads bridge to sync vacli)
    create(request)            -> to_thread(VacliVMVMBackend(cfg).__enter__);
                                  store {id -> backend}; return obj with `.id`
    wait_for_creation(id)      -> no-op (lease + tunnel already up after create)
    execute_command(id, cmd, working_dir=None, timeout=...)
                               -> to_thread(backend.run_bash(cmd, timeout));
                                  map BashResult -> namespace(stdout=, stderr=);
                                  if status == timeout -> raise CommandTimeoutError
    delete(id) / bulk_delete   -> to_thread(backend.destroy)
    teardown()                 -> destroy all live backends
```

## 6. Interface contracts

### 6.1 What `SandboxEnv` calls on the client
`create`, `wait_for_creation`, `execute_command`, `delete`, `bulk_delete`,
`teardown`. We implement exactly these. (No `upload_file`, no background jobs,
no interception — those belong to the excluded paths.)

### 6.2 CreateSandboxRequest -> VacliVMVMConfig mapping
`SandboxEnv` builds a `prime_sandboxes.CreateSandboxRequest`. The client reads
the fields it needs and ignores the rest:

| CreateSandboxRequest | VacliVMVMConfig |
|----------------------|-----------------|
| `docker_image`       | `image_url`     |
| `cpu_cores`          | `cpu_cores`     |
| `memory_gb`          | `memory_gb`     |
| `disk_size_gb`       | `disk_size_gb`  |
| `timeout_minutes`    | lease ttl       |
| `environment_vars`   | container env   |
| `labels`             | labels          |

Tenant id / lease ttl / per-command timeout come from `load_environment` args.

### 6.3 BashResult -> execute_command result
vacli `run_bash` returns a `BashResult` dict (`output`, `status`, `error_type`,
`exit_code`); it does **not** raise on timeout. Adapter:
- `status == "success"` (exit 0) or `"error"`/`error_type=="exit"` (nonzero) ->
  return `namespace(stdout=output, stderr="")` (SandboxEnv combines them).
- `status`/`error_type` indicating timeout -> raise
  `prime_sandboxes.CommandTimeoutError` so `SandboxEnv.bash` reports a timeout.
- other session errors -> raise `vf.SandboxError`.

## 7. Vendoring scope

Server-backed path requires copying (minimal, self-contained):
- `VacliLease` (lease + x2p tunnel bring-up, retries, concurrency semaphore)
- `VacliSession` + the **in-container remote server** module
  (`apps/rl/utils/remote/` session/client/server) deployed inside the VM
- `VacliVMVMBackend` + `VacliVMVMConfig`
- `errors.py` (`BackendInitError`), `BashResult`/`SessionOutput` types,
  the `_bash_result` helper

All copied under `environments/vmvm_swe/_vacli/` with provenance noted. Drift
risk accepted (snapshot, not a live import).

## 8. Env, dataset, reward

- `VMVMSandboxEnv(vf.SandboxEnv)`: overrides `__init__` to set
  `self.sandbox_client = VMVMSandboxClient(...)` and `get_sandbox_request` to
  build the request from task `info` (per-task docker image).
- `load_environment(dataset_path, tenant, image, cpu_cores, memory_gb,
  disk_size_gb, command_timeout, ...)` -> returns the env.
- Dataset: Harbor/TB task directory (instruction + test command per task), mapped
  to verifiers rows `{question, answer, info:{image, test_cmd, ...}}`.
- Reward: `run_task_tests_reward(state)` -> `execute_command(test_cmd)` in the VM
  after submit; reward = pass/fail (or scaled).

## 9. Deliverables

1. `environments/vmvm_swe/vmvm_swe/client.py` — `VMVMSandboxClient`.
2. `environments/vmvm_swe/vmvm_swe/env.py` — `VMVMSandboxEnv` + `load_environment` + rubric.
3. `environments/vmvm_swe/vmvm_swe/_vacli/` — vendored vacli code (section 7).
4. `environments/vmvm_swe/pyproject.toml` — installable; deps: `verifiers`, `prime-sandboxes`.
5. `examples/vmvm_swe/rl.toml` — references `id = "vmvm-swe"`.
6. Tests: unit (stub `subprocess` via vacli's `subprocess_mod` seam) + live smoke
   (`create -> run_bash("echo hi") -> destroy`).

## 10. Phases

- **P1 Client + smoke:** build `VMVMSandboxClient`; prove `create ->
  execute_command -> delete` against the real VMVM pool standalone.
- **P2 Env wrap:** `VMVMSandboxEnv` + trivial reward; `vf` eval on 1-2 tasks.
- **P3 PRIME-RL wire:** example TOML; run orchestrator vs a debug inference
  server; confirm trajectories + reward populate.
- **P4 Real reward + run:** wire task-test reward; small RL run.

## 11. Risks

- **Vendor drift:** copied vacli code can fall behind amaia-collab. Mitigate with
  a provenance header (source path + commit) and a periodic diff check.
- **Server-backed bring-up:** the in-container remote server adds moving parts vs
  NoServer; smoke test P1 gates this.
- **Concurrency at scale:** vacli lease bursts trigger FAAS tunnel timeouts;
  reuse the vendored `MAX_CONCURRENT_LEASES` semaphore and jittered retries.
- **Async/thread bridge:** ensure thread-pool sizing matches
  `sandbox_client_max_workers` so high `max_inflight_rollouts` doesn't starve.

## 12. Out of scope

- Interception-based harnesses (`mini-swe-agent-plus`, `terminus-harbor`).
- `upload_file` / background-job client methods.
- Multi-node env-server (`address=`) deployment — revisit if trainer nodes
  cannot reach the VMVM pool.
