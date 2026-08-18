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
`SandoqRuntime` completes the Verifiers contract with `host_tunnel = "modal"`
by default: a temporary Modal SSH relay publishes the host interception port to
the sandbox. It does not use Prime Sandbox or require `PRIME_API_KEY`.
`host_tunnel = "prime"` is available only as an explicit opt-in.

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
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch sandoq --n-concurrent 8
```

Pier's adapter materializes the DeepSWE verifier Dockerfile inside a separate
Sandoq runtime. Hidden tests are never copied into the agent runtime.
