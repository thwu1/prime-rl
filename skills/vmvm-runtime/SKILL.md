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

Do not run VMVM evaluation drivers on a login node. Validate the real provider
contract with:

```bash
sbatch user/tianhaowu/deepswe_vmvm/run_runtime_smoke.sbatch
```

The smoke checks a real lease, binary file round trip, workdir execution, the
container-to-host interception route, and cleanup. The host route is an SSH
reverse forward on VM loopback plus a VM bridge relay; the container URL must
bypass its HTTP proxy through `NO_PROXY`.

Pier's DeepSWE adapter supports prebuilt agent images and the benchmark's
separate verifier Dockerfiles. It validates the Dockerfile, starts its `FROM`
image, copies the hidden verifier files only into the verifier runtime, and
executes its `RUN` steps. Non-agent commands clear inherited proxy variables so
test behavior matches the no-network verifier contract.

Validate one reference solution before the full oracle:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch vmvm \
  --n-concurrent 1 --n-tasks 1 --sample-seed 0 \
  --name deepswe-v1.1-oracle-smoke
```

Never replay an agent command after an uncertain transport result. A nonnegative
exit code is the command result; a negative exit code is surfaced as
`SandboxError`, allowing rollout-level retry policy to decide whether to start a
fresh attempt. Cleanup remains idempotent and closes every active bridge before
releasing the vacli lease.

VMVM interception does not create a Prime sandbox or require Prime tunnel
credentials. Arbitrary public port exposure from a VMVM container is not yet a
supported provider capability; colocated servers and the harness interception
path do not need it.
