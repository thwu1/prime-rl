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

PR 17 intentionally leaves its agent-inside reverse tunnel as future work.
`SandoqRuntime` completes the generic Verifiers contract with
`host_tunnel = "modal"` by default: a temporary Modal SSH relay publishes an
arbitrary host interception port to the sandbox. It does not use Prime Sandbox
or require `PRIME_API_KEY`. `host_tunnel = "prime"` is available only as an
explicit opt-in.

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
  --n-concurrent 64 --max-retries 6
```

The OCI smoke checks lease/authentication, nested-container startup, configured
workdir creation, binary I/O, command execution, and cleanup. It deliberately
skips the generic `host_endpoint` fallback so this eval gate creates no Modal
relay. The already-passing `environment` smoke retains the generic tunnel
contract check. The subsequent one-task DeepSWE model smoke proves the actual
Sandoq-to-`ram-inference-gateway` path used by evaluation.

DeepSWE uses a fresh outer Sandoq pod for every trial by setting
`OCI_RUNNER_POOL_MAX_REUSE_COUNT=1` and disabling the per-pod image cache.
Its task images are large and unrelated; retaining them across assignments
under podman's `vfs` storage can exhaust the pod's 60 GiB ephemeral disk and
evict an otherwise live session. The pool still coordinates concurrent lease
creation, but retires each outer pod after its assignment.

An initial wave may log retryable HTTP 429 `No available pods` while the
`oci-runner` warm pool scales. Do not cancel while requests are still within the
bounded create deadline; successful capacity appears as `OCI runner assignment
acquired`. A pre-start `session_not_found` 404 poisons and deletes that outer
assignment, and Pier may retry the whole trial up to the configured six-retry
bound. The oracle gate is valid only if the terminal aggregate has 113 rewards
of 1 and zero remaining errors; transient retry lines alone are not failures.
Nested image-pull status polling tolerates 20 consecutive control-plane errors
before discarding the assignment. This polling is read-only and safe to repeat.
A definitive `session_not_found` is different: the session identity no longer
exists, so poison that assignment immediately and retry the whole trial on a
fresh lease rather than polling or replaying commands against it.
Pier treats artifact collection as best-effort, but a Sandoq transport failure
there is not a valid empty submission. The runtime adapter retains the first
`SandboxError` and surfaces it during environment cleanup so Pier rerolls the
trial instead of recording a completed reward of zero.
Directory uploads build a temporary tar archive; read and upload that archive
before leaving its `TemporaryDirectory` scope. A missing local upload archive
is a harness bug, not retryable Sandoq infrastructure.
The Pier retry allowlist is infrastructure-only: `SandboxError`,
`EnvironmentStartTimeoutError`, and `AgentSetupTimeoutError`. A known command
exit, model failure, verifier failure, or malformed reward is never resampled.

Pier's adapter materializes the DeepSWE verifier Dockerfile inside a separate
Sandoq runtime. Hidden tests are never copied into the agent runtime.
