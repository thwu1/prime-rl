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

Treat an oracle output directory as one immutable run. Before loading tasks,
bind either an exact clean Git dataset revision or a digest-pinned release
archive whose task-tree payload exactly matches the extracted dataset. Also
bind the ordered task selection, task/image-manifest hashes, clean source and
runtime pins, network semantics, timeouts, concurrency, and acceptance gates in
`run_identity.json`. Every durable task row and summary must carry that identity
digest. A resume may append invocation metadata, but must never rewrite initial
provenance or reuse a row whose identity differs; legacy unlabeled output needs
a fresh directory.

If a complete full oracle misses its minimum-valid gate, the only reusable
recovery is one `RERUN_INVALID=1` invocation from the exact same clean source,
settings, full task universe, and output directory. It retains valid rows and
reruns every non-valid row; never union separate output directories. Promotion
must strictly validate and hash-pin `invocations.jsonl`, require exact source
and run identity on every record, canonical positive-decimal unique Slurm job
IDs, strictly increasing invocation timestamps, first/resume ordering, and at
most one rerun-invalid invocation. A dependency-policy or source change
requires a new identity and a fresh full oracle rather than an in-place retry.

Apply the same immutable-run rule to model evaluations. Every non-dry launch
through `terminal_bench_vmvm/run_eval.sbatch` must declare its role (`smoke`,
`tb4`, or `mobius`), metadata deployment ID, expected model, exact deployment
spec and passed readiness checkpoint with external file hashes, dataset
authority, and an independently approved task manifest. The launcher publishes
`eval_run_identity.json` before the first model call. Guarded Kimi smoke, TB4,
and Mobius runs must reject nonempty `RESUME_DIR` before mutating output,
identity, or invocation metadata; interrupted runs require a fresh output
directory. Their guard receipt must bind exactly one well-formed invocation
record with `resume=false`, matching role/identity, and a canonical positive
Slurm job ID. A TB4 run additionally
requires the passed two-task transcript-smoke checkpoint. A Mobius run requires
the post-resize capacity-smoke checkpoint and a write-once launch certificate
that independently reconstructs the full chain: final oracle promotion receipt,
qualified TB4 result, post-resize readiness, capacity smoke, production config,
2,500-task manifest, dataset/image pins, and effective lease-start concurrency.
Use the external SHA-256 of each certificate file in launcher environment
variables, not the certificate's embedded canonical-body digest. Keep
certificates outside a Git worktree, and verify the Mobius certificate before
creating the output directory or contacting inference.
For every role, reject model and direct/base-URL overrides: load only the
deployment-local `proxy_info.json` whose resolved parent is the same exact
directory as the bound `spec.yaml`. Bind its resolved path and full-file
SHA-256 plus a canonical secret-free authority digest in readiness, eval
identity, smoke, TB4, capacity-smoke, and launch-certificate artifacts. Never
persist its URL, API key, or a standalone hash of the API key in that endpoint
record. The readiness gate establishes the proxy hash; downstream wrappers
must reuse that value, rehash before and after each stage, and reject endpoint
rotation rather than blessing it. The run validator must match the live
readiness and capacity-smoke artifact paths and file hashes to the records
embedded in the launch certificate.
Also bind the exact serving generation from status schema v4: each canonical
positive Slurm endpoint job ID, worker `started_at`, and SHA-256 digest of its
status-derived backend API base; the coordinator job ID and `started_at`; and
the proxy job ID and `first_ready_at`. Require the status proxy job to match
`proxy_info.json`, use one backend-URL canonicalizer for status and probe
headers, and reject regressing coordinator ticks. The readiness probe's
discovered backend digests must exactly match that set. Require strict tick
advancement between same-incarnation readiness polls and across the probe;
during evaluation, require progress within 30 seconds at the ten-second poll
cadence. Readiness must obtain the same status generation again after the semantic probe. Every
non-dry evaluator must verify the generation before model traffic, poll it
throughout the evaluator lifetime, and check it after child exit; terminate
and wait for the evaluator process group on route change, unavailable status,
endpoint preemption, a surviving descendant after leader exit, SIGTERM, or
SIGINT. Ignore repeated termination signals during cleanup. Remove any stale
guard receipt before spawn and publish a fresh atomic mode-0600
`route_guard_success.json` only after child exit zero, final route verification,
and stable hashes of the eval identity, invocation ledger, and results. Smoke,
TB4, capacity, and launch certificates must rehash and link this receipt. The same guard must revalidate
`proxy_info.json` and the generated LiteLLM policy on every poll.

Kimi deployment specs must contain typed integer
`spec.proxy.config.request_timeout: 7200` and `num_retries: 0`. Independently
parse `proxy_litellm_config.yaml` with a duplicate-rejecting safe YAML loader,
reject aliases/merge keys and quoted or tagged type confusion, require the
same typed values, and bind its
full-file SHA-256 without recording its URL, key, or contents. That generated
file is mutable across an intentional resize: retain each readiness/certificate
generation's own hash, compare stable policy values across generations, and
only require the current file to match the currently active readiness record.

When auditing a production trace file interactively, pass
`audit_traces.py --aggregate-only`; this reports counts and stable problem codes
without emitting trace IDs or task identifiers. The write-once smoke and TB4
certificate modes are aggregate-only by construction. Kimi qualification also
requires every hash-verified captured `/chat/completions` request to specify
`model=Kimi-K3`, `reasoning_effort=max`, and exactly the two enabled thinking
flags, and every parsed provider response to identify `Kimi-K3`. Request-side
evidence proves that max reasoning was requested; provider-side proof that it
was honored requires separate server attestation.

The required order is readiness and state-reuse gate, two-task transcript
smoke, full 66-task TB4 pass@1 audit, deployment resize, fresh readiness gate,
capacity smoke at or above production concurrency, Mobius launch-certificate
creation, and only then the 2,500-task rollout. The full TB4 qualification uses
four active rollouts and two simultaneous lease starts. Normalize effective
lease-start concurrency as the smaller of `VACLI_MAX_CONCURRENT_LEASES` and the
configured rollout concurrency, and bind that value in both the eval identity
and the downstream certificate.
The server-pinned `cpu-132-021_8103` lane is a separate 24-route contract: its
TB4 config uses 24 active rollouts, 24 HTTP connections, zero queued requests,
and two simultaneous lease starts. Its launcher requires explicit private
readiness and smoke checkpoint paths, plus a promotion-certificate path for
Mobius, and rejects resume. TB4 shard plans derive their accepted rollout and
HTTP concurrency from the pinned base config, allowing only the shared value 4
or this server-lane value 24; never rewrite a server shard to the shared value
4. Run its TB4 certificate audit with expected rollout concurrency 24 and
lease-start concurrency 2. The 24/2 audit and every shard certificate require
the bound smoke checkpoint to qualify exactly 24 rollout, multiplex, and HTTP
slots with two lease starts, and to observe peaks of exactly 24 active rollouts
and two lease starts across at least 24 traces. The shared 4/2 lane keeps its
existing two-task transcript-smoke policy.
Configured limits do not prove achieved capacity. Guarded VMVM evaluators must
publish the aggregate-only, mode-0400 `concurrency_telemetry.json` at clean
interpreter exit. It measures the peak count of holders of the vacli lease-start
semaphore. Independently, the capacity audit measures overlap from each
completed trace's setup start through scoring end, a conservative lower bound
on active rollouts. The capacity-smoke certificate must bind and rehash both
sources, require both measured peaks to reach their configured limits, and the
Mobius launch certificate must reconstruct the same evidence before it can
authorize production. Set `SMOKE_REQUIRED_ROLLOUT_CONCURRENCY` and
`SMOKE_REQUIRED_LEASE_START_CONCURRENCY` on the capacity-smoke audit. Leave both
unset for the two-task transcript smoke: it binds the observed telemetry but is
not itself a capacity qualification.
The launch certificate must prove that TB4 used exactly one route, the
post-resize deployment-spec digest differs from the TB4 digest, and the
post-resize spec/readiness route count is strictly larger and at least two.
The initial production target is exactly two routes, so invoke the
post-resize waiter with `EXPECTED_ROUTES=2` before the concurrency-eight,
lease-starts-four capacity smoke. A route-generation change invalidates the
current eval identity; do not resume guarded Kimi outputs at all.

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
