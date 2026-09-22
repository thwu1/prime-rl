---
name: sandoq-runtime
description: Configure and validate the Verifiers v1 Sandoq runtime, the PR-17 OCI provider, CPU-node gateway connectivity, and DeepSWE oracle/model evaluations.
---

# Sandoq runtime

`verifiers.v1.runtimes.SandoqRuntime` follows the same Runtime contract as
Modal: lifecycle, foreground/background execution, binary reads and writes,
host inference reachability, and cleanup. Generic/model commands are
single-attempt. An OCI gateway response whose execution status is unknown is
raised as `SandboxError`; it is never replayed in the same sandbox.

`SandoqRuntime` retains `host_tunnel = "modal"` as its general default, while
the f7313db4 integration also provides `host_tunnel = "sandoq"` for an
agent-inside Firecracker run. The native path opens parked reverse-tunnel
WebSockets and requires the staged Sandoq client, a named `tunnel` port, nested
host networking, and an explicit loopback guest URL. `host_tunnel = "prime"`
remains available only as an explicit opt-in.

DeepSWE model evaluation does not exercise that generic tunnel. Following the
RAM Harbor Sandoq backend, the CPU eval driver registers its authenticated
capture proxy with `ram-inference-gateway`, and MiniSWE calls the gateway's
stable public URL from the Sandoq task container. Thus a DeepSWE Sandoq model
run needs neither a Modal relay sandbox nor Prime tunneling; only a standalone
Runtime `host_endpoint` contract smoke uses the configured fallback.

The provider implementation is pinned as the `deps/sandoq-provider` submodule
at PR 17. Install its official client into the shared target with:

```bash
sbatch user/tianhaowu/deepswe_modal/setup_sandoq_client.sbatch
```

CPU nodes reach the Sandoq gateway directly with mTLS, while their inherited
proxy and `fwdproxy` hostname are unusable. DeepSWE launchers use a loopback
CONNECT tunnel through `provider_environment_context`; do not remove it or
patch the installed official client.

Validate a deployed environment with:

```bash
sbatch user/tianhaowu/deepswe_sandoq/run_runtime_smoke.sbatch environment
```

The smoke explicitly unsets `PRIME_API_KEY` and checks the relay from inside
the Sandoq sandbox in addition to lifecycle, binary I/O, workdir, and cleanup.

DeepSWE requires `mode = "oci-runner"` because each task has a distinct image.
The external bearer token must be a regular mode-0600 file at:

```text
/home/tianhaowu/.config/oci-runner/token
```

Then validate the OCI contract and oracle:

```bash
sbatch user/tianhaowu/deepswe_sandoq/run_runtime_smoke.sbatch oci-runner
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch sandoq \
  --n-concurrent 64 --max-retries 6 \
  --sandbox-timeout-sec 14400 --verifier-timeout-multiplier 4
```

The OCI smoke checks lease/authentication, nested-container startup, configured
workdir creation, binary I/O, command execution, and cleanup. It deliberately
skips the generic `host_endpoint` fallback so this eval gate creates no Modal
relay. The already-passing `environment` smoke retains the generic tunnel
contract check. The subsequent one-task DeepSWE model smoke proves the actual
Sandoq-to-`ram-inference-gateway` path used by evaluation.

DeepSWE uses a fresh outer Sandoq pod for every trial by setting
`OCI_RUNNER_POOL_MAX_REUSE_COUNT=1` and disabling the per-pod image cache.
Its task images are large and unrelated. The launcher enables
`OCI_RUNNER_PODMAN_FUSE_OVERLAYFS=1`, which stages the CPU node's
`fuse-overlayfs` plus `libfuse3` into each fresh outer pod and selects a separate
overlay graphroot before any task image is pulled. This avoids `vfs` copying the
complete lower filesystem once per image layer and exhausting the pod's 60 GiB
ephemeral limit. The pool still coordinates concurrent lease creation, but
retires each outer pod after its assignment.

The managed outer pod does not delegate a cgroup to nested `runsc` containers.
The provider therefore records the Pier resource request and sets common Go,
OpenMP/BLAS, joblib, Rayon, and Polars thread-count variables to
`ceil(cpu_cores)` on the task container. Without this process-level CPU view,
tasks can see all 64 host CPUs, oversubscribe the pod, run far slower than the
declared timeout, or make timing-sensitive baseline tests fail.

Agent and verifier commands use a guarded fire-and-poll protocol. The provider
launches each command once, writes its exit status and output under a unique
directory in the nested container, and polls with short persistent-shell calls.
This avoids the Sandoq gateway request-duration ceiling: an early HTTP timeout
must not be treated as a two-hour command timeout or force an entire reroll.
The guarded launch can safely retry transport errors because the same command
directory prevents duplicate execution. Status polling treats HTTP 502, 503,
and 504 as transient; none of them reruns the underlying command.

Sandoq's nested runtime can execute CPU-heavy verifier suites more slowly than
local Docker. Use Pier's supported verifier timeout multiplier instead of
treating a progressing test as a sandbox failure. The full eval TOML and oracle
command use `4.0`; keep the Sandoq session timeout at 14,400 seconds so the
scaled verifier still fits inside the sandbox lifetime.

An initial wave may log retryable HTTP 429 `No available pods` while the
`oci-runner` warm pool scales. Do not cancel while requests are still within the
bounded create deadline; successful capacity appears as `OCI runner assignment
acquired`. A pre-start `session_not_found` 404 poisons and deletes that outer
assignment, and Pier may retry the whole trial up to the configured six-retry
bound. The oracle gate is valid only if the terminal aggregate has 113 rewards
of 1 and zero remaining errors; transient retry lines alone are not failures.
Nested image-pull status polling tolerates 20 consecutive control-plane errors
before discarding the assignment. This polling is read-only and safe to repeat.
The launcher maps TOML `sandbox_startup_timeout_sec` to
`OCI_RUNNER_PULL_TIMEOUT`; the checked-in eval uses one hour for image pull plus
nested-container bootstrap, independently of the longer command/session ceiling.
A definitive `session_not_found` is different: the session identity no longer
exists, so poison that assignment immediately and retry the whole trial on a
fresh lease rather than polling or replaying commands against it.
Pier treats artifact collection as best-effort, but a Sandoq transport failure
there is not a valid empty submission. The runtime adapter retains the first
`SandboxError` and surfaces it during environment cleanup so Pier rerolls the
trial instead of recording a completed reward of zero. A typed missing-file
error is not transport failure and must not set this sticky retry signal.
Directory uploads build a temporary tar archive; read and upload that archive
before leaving its `TemporaryDirectory` scope. A missing local upload archive
is a harness bug, not retryable Sandoq infrastructure.
The Pier retry allowlist is infrastructure-only: `SandboxError`,
`EnvironmentStartTimeoutError`, and `AgentSetupTimeoutError`. A known command
exit, model failure, verifier failure, or malformed reward is never resampled.

Pier's adapter materializes the DeepSWE verifier Dockerfile inside a separate
Sandoq runtime. Hidden tests are never copied into the agent runtime.

## Provider-mode boundary

Keep the two SDK-backed adapter modes distinct. `VF_SANDBOX_PROVIDER=sandoq`
leases a predeployed Environment selected with `SANDOQ_DEFAULT_ENVIRONMENT` or
`SANDOQ_ENV_MAP` and relies on the official client's mTLS discovery; it does
not read `SANDOQ_AUTH_TOKEN` or `OCI_RUNNER_*`. It is not a drop-in executor for
heterogeneous Harbor row images unless every image has an approved deployed
Environment mapping.

Per-task Harbor images use `VF_SANDBOX_PROVIDER=oci-runner`. The isolated
Firecracker profile is
`configs/provider_context/use2/kimi_sandoq_firecracker_no_network.json`: it
sets environment `oci-runner-firecracker`, nested task network `none`, and
disables Docker Hub fallback. Its bearer lives only in the owner-only,
mode-0600 file named by `OCI_RUNNER_TOKEN_FILE`; never put the value in a repo,
TOML, command line, log, or receipt. The supervisor removes ambient
`SANDOQ_AUTH_TOKEN` and `FIRECRACKER_KEY` before launching the child.

Keep public-network TB4 on its separately hashed legacy `oci-runner` profile.
Do not use a capacity or recovery receipt from one provider profile to promote
the other.

The no-network Firecracker profile is valid only for a host-side harness or
task-free diagnostics. Mini-SWE-Agent runs inside the task sandbox, and its
model calls plus PEP 723 dependency preparation require connectivity. Use
Mini-SWE-Agent 2.4.6 only with a separately sealed Firecracker host-network
profile and the native Sandoq reverse tunnel; never treat the no-network smoke
receipt as evidence for that distinct runtime contract.

The bounded Qwen integration gate is
`run_qwen_miniswe246_sandoq_smoke.sbatch`. It selects one approved Mobius row
by a pinned line digest, rejects security-labelled metadata without printing
the identifier or prompt, and uses
`configs/provider_context/use2/qwen_sandoq_firecracker_host.json`. Keep its
Slurm wall at exactly five minutes, `agent.step_limit=3`, environment
`oci-runner-firecracker-small`, task network `host`, and native tunnel endpoint
`127.0.0.1:8485`. The launcher must clear every upper- and lower-case ambient
HTTP proxy before supervision. It loads the Qwen deployment credential only
inside the evaluator process and writes raw traffic to owner-only artifacts.
Only the final aggregate receipt may be reported. A strict pass requires one
to three model calls, nonempty provider `reasoning_content` preserved in the
trajectory, successful observed shell actions, the exact standalone native
submission command, a positive live verifier reward, and verified cleanup.
`infrastructure_only` is intentionally distinct from that submission gate.

Use `probe_model_endpoint.py --profile qwen38-2p4t` for the reusable
credential-safe Qwen endpoint check. It reads the deployment-local proxy
metadata directly, disables ambient proxies, sends `X-Session-ID`, requests
128 tokens with a five-minute ceiling, and emits only endpoint hashes,
statuses, latencies, byte count, and reasoning/content presence flags. Never
log the loaded URL, API key, session value, or response body.

## Terminal Bench Kimi scored smoke

The server-scoped Kimi TB4 smoke must use
`configs/eval/servers/cpu-132-021_8103/tb4_kimi_k3_sandoq_smoke.toml` through
`run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch`. The launcher derives
and probes all 24 pinned workers, then exposes a loopback router using
consistent hashing on `X-Session-ID`; do not point the evaluator at the shared
front proxy.

This scored one-task smoke has a separate bounded timeout profile. Keep client
retries, whole-rollout retries, verifier-runtime retries, and router retries at
zero. Its exact timeout hierarchy is a 9,000-second rollout, 9,600-second host
harness request, and 10,800-second Sandoq session/client timeout. Submit with
an exact four-hour Slurm wall so setup, scoring, cleanup, and certificate
publication remain outside the longest blocking model request:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-<commit> && env PROJECT_DIR=\$PWD KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION=<commit> KIMI_SANDOQ_STAGE=smoke KIMI_SANDOQ_PREFLIGHT_ONLY=0 sbatch --parsable --time=04:00:00 \$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch" C-m
```

Use only the checked-in, digest-pinned non-security selector. Do not print its
contents or task identifier while validating or monitoring the run.

## Long-Kimi managed-shell recovery gate

Only the sealed `kimi-tb4-long` lease profile enables managed-shell recovery.
The server-scoped launcher derives that profile through the provider-context
supervisor; do not set `OCI_RUNNER_MANAGED_SHELL_RECOVERY` independently. The
provider rejects a mismatched declaration, and standard plus Qwen profiles keep
recovery disabled.

For this profile, non-idempotent shell POSTs remain broker-owned until their
bounded IPC response is published. Request and response frames are capped at
16 MiB, response publication has an absolute deadline, and ambiguous,
oversized, or failed publication poisons the assignment without replay. A
departed client cannot admit new work; its already-running command is allowed
to quiesce before broker-owned cleanup reaps the assignment.

Run the task-free forced-delete probe before restarting Kimi TB4, then run the
3,900-second idle-endurance probe before a full rollout. Both use a disposable,
digest-pinned utility image and access neither benchmark tasks nor a model
endpoint. The checked-in probe launcher seeds the complete pinned Python path
before provider-context supervision; do not invoke the probe module directly
or replace that path with the shared dependency target alone. Submit Slurm work
only through the launcher tmux pane:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-kimi-vmvm-<commit> && env PROJECT_DIR=\$PWD KIMI_RECOVERY_EXPECTED_PRIME_RL_REVISION=<full-commit> KIMI_RECOVERY_PROBE_SHA256=<probe-sha256> KIMI_RECOVERY_PROBE_MODE=forced-delete sbatch --parsable \$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/run_sandoq_managed_shell_recovery_probe_cpu-132-021_8103.sbatch" C-m
```

Repeat with `KIMI_RECOVERY_PROBE_MODE=idle-endurance` for the endurance gate.
A probe is valid only when its private receipt records exactly one recovery and
successful assignment cleanup plus pool drain.
