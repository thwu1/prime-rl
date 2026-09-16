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

Use the `cpu_x86` partition with `cpu_x86_lowest`; the historical `cpu` /
`cpu_lowest` names are no longer valid. Pin vacli to
`/public/fbpkgs/x86_64/vacli/stable/vacli` (or leave the backend default). The
moving `latest` build 793 launches an x2p helper with an unavailable GLIBC
symbol on some otherwise healthy CPU nodes, producing misleading repeated
lease failures. Test a candidate binary with `probe_vmvm.sbatch` before rolling
it out fleet-wide. Because the login host is ARM64 and CPU workers are x86_64,
never put the login host's `~/.local/bin/uv` first on a CPU job's `PATH`; use an
x86-specific binary or a dependency tree staged for x86_64.

Invoke vacli directly. Do not wrap it in the host `stdbuf`: the injected
`libstdbuf.so` may require GLIBC 2.38 while vacli selects an older bundled libc,
causing lease startup to fail before any VM is requested.

For Harbor tasks with Compose sidecars, retain the VMVM lease and replace the
bootstrap task container with a Podman Compose project. Start
`podman system service --time=0 unix:///run/podman/podman.sock` first because
Docker Compose is present on the VM but the Podman API socket is not enabled by
default. Resolve the `main` container after `compose up --wait`, strip terminal
color escapes before validating its container ID, and preserve service-specific
artifact bytes for isolated verifier replay. A successful `compose up` alone is
not an oracle gate: exercise a sidecar collect hook and a separate verifier VM.
Discover every Compose service name and include those DNS aliases in both
`NO_PROXY` and `no_proxy` before opening the main container's persistent shell.
Otherwise HTTP clients route healthy sidecar calls through the forward proxy
and report misleading 502 responses. Sealed, offline verifier images may add
new loopback aliases to `/etc/hosts` from `test.sh`; run their verifier command
with `NO_PROXY=*` so late aliases are also kept local.

Perform harness-owned file transfer, extraction, permission setup, and artifact
replay with `podman exec --user 0`. Keep the persistent agent shell and collect
hooks at the image's declared user unless the task explicitly requests another
user. This mirrors container-copy semantics while preserving the benchmark's
agent permission boundary.

The smoke checks a real lease, binary file round trip, workdir execution, the
container-to-host interception route, and cleanup. The host route is an SSH
reverse forward on VM loopback plus a VM bridge relay; the container URL must
bypass its HTTP proxy through `NO_PROXY`. Discover the bridge gateway from the
container network namespace on the VM host (`podman inspect` PID plus
`nsenter -n ip route`) before falling back to a route probe inside the image.
This is required for Compose networks and images without `iproute2`; silently
using the default Podman gateway makes every model call fail before sampling.
Probe the resulting route from the task container with any available TCP
client; benchmark images are not required to provide Python or Bash.

For Harbor task network policy, resolve the effective modes with Harbor's own
precedence: `[environment].network_mode` is the baseline and defaults to
`public`; explicit `[agent].network_mode` and `[verifier].network_mode` override
their respective phase; a separate verifier uses its own environment baseline.
Only translate legacy `allow_internet` when the same environment table does not
set `network_mode`. The VMVM Harbor adapter supports `public` and `no-network`.
Reject unknown modes, `allowlist`, and any phase transition that would relax an
already active `no-network` runtime back to `public` before provisioning tasks.

VMVM implements `no-network` at the untrusted agent/verifier boundary. Trusted
harness dependency preparation retains the original bridge temporarily. For a
single-container task, defer its declared image startup command until isolation
is active. Immediately before the agent program (when its host endpoint opens,
with `run_program` as a backstop), disconnect every public network and retain a
unique Podman `--internal` IPv4 network. Separate verifiers activate the same
policy immediately before `test.sh`. Compose containers share that internal
network; carry every existing declared alias plus the service name when
reattaching them. Reject an internal network with IPv6, multiple subnets, a
non-private subnet, or unexpected residual network attachments.

An internal Podman network still reaches services bound on its host gateway, so
`--internal` alone is insufficient: the injected forward proxy on gateway port
8080 remains an egress path. Install a workload-subnet-scoped INPUT chain that
allows TCP/UDP 53 for Podman's internal service-name DNS, allows each active SSH
reverse-tunnel TCP port only from the main container address, and rejects every
other gateway packet. Podman DNS on an internal network must not recurse for
external names; verify this in a live canary whenever the network stack changes.
Add and remove tunnel rules with tunnel lifetime. On partial activation, pause
all workload containers and remove any partial firewall jump/chain; normal
teardown removes tunnel rules, the chain, and the internal network idempotently.
`podman exec` and SSH control remain outside the workload network namespace and
continue to function after isolation.

Do not install shared-verifier test dependencies before the agent or Oracle
solution runs: this changes the application environment and breaks Harbor's
solution-before-verifier ordering. During trusted public setup, use `pip wheel`
to resolve and build a complete wheelhouse for every declared verifier
requirement without installing it. Move the resulting wheel-only tar to a
controller temporary directory as mode 0400 so concurrent rollouts do not retain
archives in RAM and an agent cannot modify the cached bytes. Cache by the exact
requirement tuple with async single-flight. A wheelhouse containing only
`*-none-any.whl` files can be shared across images; otherwise scope reuse to the
runtime image plus its Python implementation/version, SOABI, platform, and
machine fingerprint. Hash-check every reuse, retain controller cache entries
until process exit, and clean each sandbox copy after installation. After the
agent/solution and after `no-network` activation, re-probe all declared versions,
restore the archive, and install only missing or mismatched requirements with
`--no-index` / `PIP_NO_INDEX=1`. Fail closed on resolution, source-build,
non-wheel, integrity, offline-install, or post-install validation failure.

Some legacy corpora declare agent `no-network` while their trusted reference
`solve.sh` downloads build dependencies. Keep strict Harbor semantics as the
default oracle mode. If corpus qualification needs the historical reference
result, use an explicit oracle-only compatibility mode that leaves trusted image
startup and the solution on the setup bridge, binds that mode immutably before
resuming any task rows, records it in run/task/summary provenance, and then
activates the task's declared policy before artifact collection or verification.
Never expose this override to model setup or rollouts, and report strict-policy
and compatibility-oracle results separately.

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
fresh attempt. OpenSSH reserves exit code 255 for transport failure, so direct
root and Compose-sidecar exec paths must normalize it to a negative
`broken_pipe` result instead of treating it as a task command failure. Cleanup
remains idempotent and closes every active bridge before releasing the vacli
lease.

The generic Verifiers `VMVMRuntime.run()` owns provider-local recovery for a
structured `broken_pipe` result. It reconnects to the same container with
`restart_session()` and collects the pending FIFO command exactly once with
`recover_last()`; it never resubmits the command. It permits five consecutive
recovery drops. `PierRuntimeEnvironment` additionally recognizes unstructured
connection-loss signatures from backends that cannot emit `broken_pipe`. A lost
container, rebuilt persistent shell, or exhausted reconnect budget becomes
`SandboxError` and consumes a whole-trial retry.

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

For LiteLLM-backed multi-turn evals, send one stable rollout trace ID as both
`X-LiteLLM-Session-ID` and `X-Session-ID` on every turn. The first header drives
LiteLLM session affinity; the second is a compatibility mirror. A serving
deployment must publish `extras.sticky=true` and a Redis port, because otherwise
affinity can be isolated per proxy worker. Before a large Kimi run, query
model-specific health before and after a semantic route snapshot, require the
exact intended route count with zero unhealthy routes, reject hidden retries,
and verify sequential same-session requests retain their backend. Never request
`logprobs`, `prompt_logprobs`, or `top_logprobs` from the affected Kimi runtime.
Omit `return_token_ids` as well when the workflow only requires response and
reasoning transcripts. A semantic snapshot detects already-corrupt workers but
does not substitute for a compatible KDA patch plus piecewise CUDA graphs (or
eager execution).

For the pinned Qwen TB4 deployment, use
`user/tianhaowu/terminal_bench_vmvm/run_qwen_direct_eval.sbatch` when the shared
LiteLLM deadline is too short for a model turn. It validates and snapshots all
16 non-secret endpoint metadata files, probes every direct worker, then runs a
loopback-only consistent-hash `vllm-router` with retries disabled. Stage that
router into its separate versioned x86 directory with
`stage_qwen_direct_router.sh`; never add it to or overwrite the live evaluator
dependency directory. Keep Qwen rollout concurrency, multiplexing, HTTP pools,
router admission, and aggregate VMVM concurrency at eight or less. Do not run
the fallback concurrently with another VMVM evaluation that already consumes
that budget. The launcher must reject configs without an externally approved,
SHA-256-pinned task allowlist and must never accept inline task selections. The
approval path and digest must be supplied independently through
`DIRECT_QWEN_APPROVED_TASK_FILE` and
`DIRECT_QWEN_APPROVED_TASK_FILE_SHA256`; require their contents to match the
config's pinned task-file digest. Resume only through the direct wrapper so the
saved worker manifest and loopback endpoint are revalidated.

`VACLI_IMAGE_PULL_TIMEOUT_SECONDS` bounds each VM-side image pull attempt. The
DeepSWE launcher derives it from TOML `sandbox_startup_timeout_sec` and uses one
hour by default; keep the command/session ceiling separate because verification
can legitimately outlive startup.
Use `verifier_timeout_multiplier = 4.0` in full VMVM TOMLs and
`--verifier-timeout-multiplier 4` for the oracle. This retains the task's own
timeout ratios while allowing slow remote verifier execution to complete.
For a targeted model-eval recovery, set top-level TOML `task_names` to exact
task directory names. Do not use Pier's generated `trial-name__SUFFIX` value.
