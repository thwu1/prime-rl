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

`VACLI_MAX_CONCURRENT_LEASES` limits simultaneous lease and reverse-forward
setup through one process-wide slot pool. A slot is released as soon as setup
and its readiness probe complete, so it does not cap the number of active
VMVMs or live host tunnels. For a high-fanout run, set the evaluator's worker
count to the desired active concurrency. The DeepSWE launchers default to 113
active trials while capping simultaneous VMVM setup at 32; set
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
solution-before-verifier ordering. For every shared verifier whose declared
policy is `no-network`, prefetch before the agent regardless of the agent's own
policy; hidden tests remain unstaged until the verifier boundary. During trusted
public setup, use `pip wheel --only-binary=:all:` to resolve a complete
wheelhouse for every declared verifier requirement without installing it or
executing sdist build hooks. Move the resulting wheel-only tar to a
controller temporary directory as mode 0400 so concurrent rollouts do not retain
archives in RAM and an agent cannot modify the cached bytes. Cache by the exact
requirement tuple with async single-flight. A wheelhouse containing only
`*-none-any.whl` files can be shared across images; otherwise scope reuse to the
runtime image plus its Python implementation/version, SOABI, platform, and
machine fingerprint. Hash-check every reuse, detach per-runtime references on
every terminal path, retain controller cache entries for the taskset lifetime,
and clean each sandbox copy after installation. Deterministically close the
shared cache when the evaluator or environment server exits; object finalization
is only a fallback. After the agent/solution and after `no-network` activation,
stage hidden tests, re-probe all declared versions, restore the archive, and
install only missing or mismatched requirements with
`--no-index` / `PIP_NO_INDEX=1`. Fail closed on resolution, source-build,
non-wheel, integrity, offline-install, or post-install validation failure.
For older immutable Mobius images, supplement the marked Dockerfile layer with
only literal, exactly pinned `pip install` requirements from `tests/test.sh`.
Prefetch the full merged set before the untrusted phase, accepting only exact
`name[extras]==version` operands and an explicit allowlist of semantic-neutral
zero-argument flags. The only unpinned compatibility rule is bare `pytest`,
which normalizes to the adapter's existing `pytest==8.3.4` default. Reject all
other dynamic, URL, local-path, unpinned, environment-marked, conflicting,
option-dependent, and ambiguously wrapped commands rather than silently
changing their meaning. At the verifier boundary, re-probe the full dependency
closure and perform any offline restore through the harness-owned root path
without `--ignore-installed` before re-probing from the agent shell.

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
HTTP 429, and HTTP 5xx responses may be retried there. If those retries exhaust
inside a VMVM host-endpoint context, probe the workload-to-host HTTP path with
proxies disabled before teardown: preserve the provider error while the path is
reachable, and classify it as a tunnel failure only when that post-failure probe
cannot reach the endpoint. A fresh whole-rollout attempt is reserved for this
confirmed tunnel loss or a confirmed lost VM/container before any result was
persisted.
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
dependency directory. The TB4 gate uses eight rollout slots. The qualified
2,500-task production config keeps 64 rollout/VMVM sessions active while the
shared HTTP pool and router admission are both capped at 32 with a bounded
32-request queue; simultaneous VMVM lease setup stays capped at two. Do not run
either route concurrently with another VMVM evaluation that consumes its
measured budget. The launcher must reject configs without an externally approved,
SHA-256-pinned task allowlist and must never accept inline task selections. The
approval path and digest must be supplied independently through
`DIRECT_QWEN_APPROVED_TASK_FILE` and
`DIRECT_QWEN_APPROVED_TASK_FILE_SHA256`; require their contents to match the
config's pinned task-file digest. Resume only through the direct wrapper so the
saved worker manifest and loopback endpoint are revalidated.

After a terminal 2,500-task Qwen run, use `run_qwen_repair_chain.sbatch`; never
resume the source in place. The private repair selection is the exact union of
ordinary missing/error tasks and scored-pass traces that fail the exporter's
trainability audit (retained reasoning, captured model-I/O integrity,
provider-request messages matching the persisted graph path, and the 256K
context cap). The original pass-only export must consume that same
attested selection and exclude exactly those source tasks; the merge requires
every excluded strict-invalid pass to have a passing repair replacement. Run
the controller from a clean detached exact revision with clean pinned
submodules, an externally pinned source task-file digest and provenance digest,
and new, absolute, disjoint runtime/export paths. It calls the direct evaluator
as a shell program in the same allocation, exports original and repair sources
pass-only, and atomically merges the two attested corpora. A malformed final
append without a newline is retained in the immutable physical source and its
digest, but is omitted from logical routing/export rows only when the repair
selection accounts for an owed task; complete malformed rows still fail. A
valid final JSON object remains a logical row even without its newline. Repair
exports cross-bind each task name and index to the evaluator order of the
approved repair universe. Before merge, the controller binds both finalized
export manifests and complete export-tree digests; the merger rejects any
later tree mutation and any repair task outside the selected union. A
zero-owed plan publishes the original export only. Treat task entries as opaque
and never add semantic or name-based filtering. The selection manifest, its
union/category files, and the repair export's copied selection and attestation
sidecars must remain regular mode-0600 files and byte-identical to their pinned
inputs. Child logs are private mode 0600, while console output is restricted to
aggregate counts, digests, and stable codes. Submit this state change only
through `swebench_vmvm:Launcher.0` with an `afterany` dependency on the
producer.

SFT format v3 keeps historical assistant `reasoning_content` and every sampled
assistant `finish_reason` in each expanded row, with explicit source/retained
fidelity counts. Every export and merge also carries the immutable
`target-rendering-contract.json`, which pins the Nemotron Super tokenizer
revision, the renderer repository revision, and `nemotron-3` settings with
`preserve_all_thinking=true` and `truncate_history_thinking=false`. Do not train
from an export whose contract is absent, modified, or inconsistent across merge
inputs.

Treat only exact `/chat/completions` captures as trainable. The format-v3
exporter rejects unknown graph/wire message structure, material
`provider_state`/`reasoning_details` (absent or null is allowed), sampled finish
reasons other than `stop`/`tool_calls`, non-object or lossy JSON tool arguments,
and tool schemas without an explicit `type="function"` envelope. Assistant
`content` may be omitted by Verifiers' `exclude_none` serialization.

Run `user/tianhaowu/terminal_bench_vmvm/preflight_sft.py` against the finalized
export and its expected manifest SHA before SFT. Store the mode-0600 output
outside the source checkout, then set `preflight_attestation` and
`preflight_attestation_sha256` in every format-v3 SFT data block. Use the exact
tokenizer repository/revision and renderer config in the target contract and a
sequence length no smaller than the attested maximum row and no larger than
262,144, with `pack_function="fixed_stack"` so a concatenation boundary cannot
truncate a target. The trainer rechecks all export artifacts, rerenders every
row, and revalidates code hashes, project and renderer revisions, dependency
versions, and config bindings at startup; format-v3 rows cannot bypass the gate
through the generic SFT loader.

`VACLI_IMAGE_PULL_TIMEOUT_SECONDS` bounds each VM-side image pull attempt. The
DeepSWE launcher derives it from TOML `sandbox_startup_timeout_sec` and uses one
hour by default; keep the command/session ceiling separate because verification
can legitimately outlive startup.
Use `verifier_timeout_multiplier = 4.0` in full VMVM TOMLs and
`--verifier-timeout-multiplier 4` for the oracle. This retains the task's own
timeout ratios while allowing slow remote verifier execution to complete.
For a targeted model-eval recovery, set top-level TOML `task_names` to exact
task directory names. Do not use Pier's generated `trial-name__SUFFIX` value.
