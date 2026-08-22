---
name: vmvm-runtime
description: Configure, validate, and debug the Verifiers v1 VMVM runtime backed by vacli and vmvm_tb_v2. Use for type=vmvm evals, VMVM lease failures, reverse SSH interception, or the VMVM CPU smoke test.
---

# VMVM runtime

The first-class provider is `verifiers.v1.runtimes.VMVMRuntime`. It follows the
same `Runtime` contract as Modal: provision, run foreground/background commands,
read/write bytes, reach the host interception server, and release the sandbox.
The implementation uses `vmvm_tb_v2` only for vacli lease, SSH, and Podman
operations.

Select it in an eval TOML:

```toml
[harness.runtime]
type = "vmvm"
session_timeout = 2100
tenant_id = "async_2347641"
lease_ttl = "60s"
```

The local backend package must be importable by the CPU evaluator:

```bash
export PYTHONPATH="$PWD/environments/vmvm_tb_v2${PYTHONPATH:+:$PYTHONPATH}"
```

`VACLI_MAX_CONCURRENT_LEASES` limits only simultaneous lease bring-up. It does
not cap the number of active VMVMs after their tunnels are ready. For a
high-fanout run, set the evaluator's worker count to the desired active
concurrency. The DeepSWE launchers default to 113 active trials while capping
simultaneous VMVM lease acquisition at 32; set
`VACLI_MAX_CONCURRENT_LEASES` explicitly to override that startup fanout.

Do not run VMVM evaluation drivers on a login node. Validate the real provider
contract with:

```bash
sbatch user/tianhaowu/deepswe_vmvm/run_runtime_smoke.sbatch
```

The smoke checks a real lease, binary file round trip, workdir execution, the
container-to-host interception route, and cleanup. The host route is an SSH
reverse forward on VM loopback plus a VM bridge relay; the container URL must
bypass its HTTP proxy through `NO_PROXY`. Probe the bridge from the task
container with Bash's `/dev/tcp`; benchmark images for Go, Java, Rust, and
TypeScript are not required to provide a `python` executable.

Pier's DeepSWE adapter supports prebuilt agent images and the benchmark's
separate verifier Dockerfiles. It validates the Dockerfile, starts its `FROM`
image, copies the hidden verifier files only into the verifier runtime, and
executes its `RUN` steps. Non-agent commands clear inherited proxy variables so
test behavior matches the no-network verifier contract.
Commands use a non-login shell, matching Pier's Modal executor. A login shell can
replace the image `PATH` and hide tools installed in an image virtual environment
such as `/opt/venv/bin`.

Validate one reference solution before the full oracle:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch vmvm \
  --n-concurrent 1 --n-tasks 1 --sample-seed 0 \
  --sandbox-timeout-sec 14400 --verifier-timeout-multiplier 4 \
  --name deepswe-v1.1-oracle-smoke
```

`--task-name` takes the task directory name, not the namespaced result name. For
example, target the memory-heavy SCC gate with:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch vmvm \
  --n-concurrent 1 --task-name scc-bounded-memory-spilling \
  --name deepswe-v1.1-oracle-scc
```

Task CPU and memory declarations are enforced on the Podman container. The
current VMVM tenant supplies about 4 GB of physical RAM, so requests above that
are backed by a per-lease swapfile on the VM's dedicated XFS container-storage
disk. The VM root and `/var/tmp` are overlayfs and cannot host swapfiles; using
them fails with `swapon: Invalid argument`. Keep 512 MiB outside the requested
container memory for VM services. A Go verifier ending in `signal: killed`
usually means this host-memory setup did not take effect.

Never replay an agent command after an uncertain transport result. A nonnegative
exit code is the command result; a negative exit code is surfaced as
`SandboxError`, allowing rollout-level retry policy to decide whether to start a
fresh attempt. Cleanup remains idempotent and closes every active bridge before
releasing the vacli lease.

The DeepSWE Pier adapter adds provider-local recovery without changing the
generic Runtime or VMVM-TB-v2 interfaces. When `runtime.run()` reports a VMVM
connection loss, `PierRuntimeEnvironment` reconnects to the same container with
the existing `restart_session()` and collects the pending FIFO command exactly
once with `recover_last()`. It permits five consecutive recovery drops. A lost
container or persistent shell still becomes `SandboxError` and consumes a
whole-trial retry.

If the in-flight command depends on a registered host tunnel,
`restart_session()` must restore that reverse forward on the replacement SSH
control master before `recover_last()`. Keep the same remote port so the
surviving command's endpoint remains valid; failed forward restoration makes
the sandbox event unrecoverable.

If a worker exits with a nonnegative code and emits its final status/reward JSON
to stdout, but the result-file read then loses transport, recover that immutable
summary instead of replaying the rollout. Treat the event as fatal when neither
the result file nor a matching final stdout summary is available.
Snapshot the worker and its runtime inputs before starting leases, and build
replacement VMVMs from that run-local snapshot. Source edits during a long run
must not silently change later tasks. If one task exhausts confirmed-safe
infrastructure retries, record it as missing and let unrelated queued tasks
finish before failing the aggregate run.

Stage and validate files in the container before opening a long-lived reverse
host tunnel. A transfer started after `open_host_tunnel()` can block behind the
SSH control connection; making the tunnel the last setup step avoids that stall.

Keep model-provider retries inside the individual model call. Transport errors,
HTTP 429, and HTTP 5xx responses may be retried there, but exhausting those
retries is not evidence that the sandbox was lost and must not replay the whole
rollout. Score or surface the terminal provider failure according to the
benchmark contract. A fresh whole-rollout attempt is reserved for a confirmed
lost VM or container before any result was persisted.
Classify provider-specific context-limit wording before generic retry handling.
In particular, Nemotron/vLLM may report that the model's "context length is
only" a given size and ask to "reduce the length of the input prompt". That is
a context reset, not ten retries followed by a model error.

Do not enable `set -e` inside a command passed to the persistent
`VacliVMVMBackend.run_bash` shell. A failing child then exits the shell before
the backend's completion sentinel is emitted, so an ordinary command failure is
misreported as a timeout. Capture and propagate the child status explicitly;
`set -o pipefail` is safe when needed.

VMVM interception does not create a Prime sandbox or require Prime tunnel
credentials. Arbitrary public port exposure from a VMVM container is not yet a
supported provider capability; colocated servers and the harness interception
path do not need it.

Plain HTTP egress from a VMVM lease can be transparently intercepted by Meta's
forward proxy. In that path, an origin-form request such as `GET /v3/health`
fails with `400 No uri specified`; send proxy-form requests with the complete
URL instead. Configure an explicit HTTP proxy for clients such as urllib, and
keep the reverse-tunneled host/model address in `NO_PROXY`. Do not use
`urllib.request.ProxyHandler({})` or an `httpx` client with `trust_env=False`
and no explicit proxy for traffic that requires the lease's injected
`HTTP_PROXY`. Resolve that proxy and pass it explicitly to urllib, httpx, and
WebSocket clients. Disabling environment proxies remains appropriate for calls
to the reverse-tunneled model endpoint itself.
The forward proxy may cache GET responses despite `Cache-Control: no-cache`;
append a unique query parameter to mutable polling URLs such as execution status.

DeepSWE model traffic does not use a Modal relay or VMVM's per-sandbox host
tunnel. The CPU eval driver registers its authenticated capture proxy with the
shared `ram-inference-gateway`, and the MiniSWE process in each VMVM calls that
stable public ingress. VMVM's reverse-SSH `host_endpoint` remains available for
generic Runtime consumers and its contract smoke.

`VACLI_IMAGE_PULL_TIMEOUT_SECONDS` bounds each VM-side image pull attempt. The
DeepSWE launcher derives it from TOML `sandbox_startup_timeout_sec` and uses one
hour by default; keep the command/session ceiling separate because verification
can legitimately outlive startup.
Use `verifier_timeout_multiplier = 4.0` in full VMVM TOMLs and
`--verifier-timeout-multiplier 4` for the oracle. This retains the task's own
timeout ratios while allowing slow remote verifier execution to complete.
For a targeted model-eval recovery, set top-level TOML `task_names` to exact
task directory names. Do not use Pier's generated `trial-name__SUFFIX` value.
