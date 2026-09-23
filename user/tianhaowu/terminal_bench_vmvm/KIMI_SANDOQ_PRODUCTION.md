# Kimi K3 Max Sandoq production lane

This is the server-scoped, pass@1 trace-generation lane for
`cpu-132-021_8103`. It selects the 2,499 non-Compose members of the approved
2,500-task Mobius oracle set and runs them through the direct Kimi router and
the Sandoq OCI runtime. Task membership remains private throughout selection,
launch, monitoring, certification, and export.

The source task metadata declares `no-network` for both agent and verifier,
and selection preserves that declaration. Mini-SWE-Agent executes inside the
sandbox, however, so this lane uses full `oci-runner-firecracker` with
provider task network `host` and the native loopback Sandoq reverse tunnel.
Its effective network is therefore public. Do not describe this as strict
no-network isolation; the declaration is a selection property, not the
effective runtime boundary.

## Fixed contracts

- Model: `Kimi-K3`, one rollout per task, 200 turns.
- Context: 262,144 tokens; at most 32,768 sampled tokens per call.
- Timeouts: 12-hour client/session, 10-hour rollout, one-hour setup and
  finalize, six-hour scoring.
- Retries: zero at the client, router, rollout, and verifier layers.
- Infrastructure recovery: after an otherwise successful evaluator invocation,
  one in-process resume may replace only missing rows or error rows that contain
  no nodes, rewards, metrics, or model metadata. Any model-bearing or ambiguous
  error fails closed, so this does not add another model attempt to pass@1.
- Capture: preserved thinking, reasoning content, model I/O, request graph,
  exact provider JSON, tool calls, and provider usage. Log probabilities and
  token IDs are intentionally not requested.
- Runtime: Mini-SWE-Agent 2.4.6 in Sandoq `oci-runner` mode, exact environment
  `oci-runner-firecracker`, `network_access=true`, provider task network
  `host`, native reverse tunnel on guest loopback, resource multiplier 1, and
  Compose disabled.
- Cleanup: verified pool drain and assignment cleanup are mandatory on every
  evaluator terminal path.

Concurrency is a launch input. It is never inferred from the router's static
maximum and cannot exceed the concurrency qualified by the exact
`direct-kimi-sandoq-capacity` certificate. The current profile has a hard
upper bound of 64, but 64 is not authorized until a matching capacity
certificate passes.

## Promotion prerequisites

Use a clean detached checkout at the exact intended production revision. All
private directories must be owned by the current user and mode 0700; private
files must be regular, single-link mode-0600 files.

Promotion requires all of the following immutable inputs:

1. A complete 66-task, pass@1, official TB4 Kimi certificate whose measured
   pass rate is in the accepted reproduction band and whose router used
   consistent hashing on `X-Session-ID` with zero retries.
2. Passed task-free forced-delete and 3,900-second idle-endurance managed-shell
   recovery receipts for the 12-hour Kimi lease profile in the same
   full Firecracker host-tunnel environment and both its cleanup/tunnel and
   minimum-resource/tunnel capability receipts.
3. A server-bound Firecracker capacity certificate for `cpu-132-021_8103`, the exact worker
   manifest/config/source hashes, zero route anomalies or capacity rejections,
   verified cleanup, and a measured concurrency no lower than the requested
   production concurrency.
4. The canonical approved 2,500-task source, canonical dataset revision, and
   digest-pinned Sandoq image manifest.
5. The pinned, sanitized Mini-SWE-Agent 2.4.6 compatibility receipt proving
   native submission, provider `reasoning_content` retention, forwarded prior
   reasoning/tool results, successful program exit, and cleanup. Tool-command
   exit success is independently required from the c64 trace audit.

Diagnostic or partial TB4 artifacts are not promotable. Never inspect or print
selector contents, task identifiers, prompts, responses, or raw task errors
while checking these gates.

The promotable MiniSWE TB4 artifact is produced by the opaque union planner,
the two `tb4-miniswe246-*-union` launcher stages, and
`finalize_tb4_kimi_k3_miniswe246_union_cpu-132-021_8103.sbatch`. The certifier
revalidates both lane artifacts and numeric tool exit-code observations before
forming the aggregate certificate; exploratory nonzero shell exits are counted
but are not themselves a trace failure.

## Materialize the opaque selector

Create a fresh private directory, then run from the clean checkout:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm --offline \
  python user/tianhaowu/terminal_bench_vmvm/kimi_sandoq_production.py \
  materialize-selector \
  --source "$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt" \
  --dataset /checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 \
  --selector /path/to/private-gate/kimi_sandoq_2499.private.txt \
  --receipt /path/to/private-gate/kimi_sandoq_2499.receipt.json \
  --private-output-root /path/to/private-gate
```

The command recomputes the partition from canonical metadata. Its public
summary and receipt contain only counts and hashes. The excluded Compose member
is neither named nor indexed.

## Promote a measured capacity

Choose the requested concurrency only after reviewing the capacity
certificate. Publish the promotion into the same kind of fresh private root:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm --offline \
  python user/tianhaowu/terminal_bench_vmvm/kimi_sandoq_production.py promote \
  --tb4-certificate /path/to/official-tb4-certificate.json \
  --tb4-certificate-sha256 TB4_SHA256 \
  --forced-delete-receipt /path/to/forced-delete.json \
  --forced-delete-receipt-sha256 FORCED_DELETE_SHA256 \
  --idle-recovery-receipt /path/to/idle-endurance.json \
  --idle-recovery-receipt-sha256 IDLE_ENDURANCE_SHA256 \
  --capacity-certificate /path/to/direct_kimi_capacity_certificate.json \
  --capacity-certificate-sha256 CAPACITY_SHA256 \
  --miniswe-compatibility-receipt /checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/qwen-miniswe246-sandoq-3step-20260921/run-1537041/receipt.json \
  --miniswe-compatibility-receipt-sha256 cee344d3c9bc3c18f602a0ad217ade7395db263d50cd8d4c428507a21de86220 \
  --requested-concurrency REQUESTED_CONCURRENCY \
  --output /path/to/private-gate/kimi_sandoq_promotion.json \
  --private-output-root /path/to/private-gate
```

Changing the endpoint, source, config, selector, image manifest, worker
manifest, or requested concurrency requires new certificates and a fresh
output namespace.

Full Firecracker is proven at 2 CPU / 4 GiB / 10 GiB with a successful
native-tunnel round trip. The production selector now reopens every selected
task's canonical metadata and binds an aggregate-only resource-vector digest:
all 2,499 selected tasks use shared verification, request no GPU, and have
agent and verifier maxima exactly equal to that qualified envelope. The lone
Compose task remains excluded. Twenty-eight of 66 TB4 tasks fit this resource envelope, but
three require Compose and cannot run on the Sandoq lane. TB4 therefore requires
the sealed 25-Sandoq / 38-VMVM CPU union, with three GPU tasks recorded as
unsupported. Production promotion still requires the TB4 score and capacity
certificate, but aggregate resource coverage is no longer an unresolved gate.

## ECR rotation and launch

The Firecracker bearer is read only from the sealed provider profile's private
token-file path; never export it as a raw environment value. The x86 evaluator
also cannot mint ECR credentials. Before submission, start
`sandoq_ecr_rotation.py rotate` as a login-side ARM64 service in a durable
session, with fresh mode-0600 token/state/event files under a mode-0700 private
directory. Keep that service running until the evaluation job is terminal.
The batch-side guard continuously validates freshness and invokes the sealed
verified-cleanup command before credential expiry or on any evaluator exit.

Submit only through the launcher's tmux pane. Set the exact clean revision,
private selector and receipt, promotion certificate, requested concurrency,
and rotator state file:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-REVISION && env PROJECT_DIR=\$PWD KIMI_PRODUCTION_EXPECTED_PRIME_RL_REVISION=REVISION KIMI_PRODUCTION_SELECTOR=/path/to/private-gate/kimi_sandoq_2499.private.txt KIMI_PRODUCTION_SELECTOR_RECEIPT=/path/to/private-gate/kimi_sandoq_2499.receipt.json KIMI_PRODUCTION_SELECTOR_RECEIPT_SHA256=SELECTOR_RECEIPT_SHA256 KIMI_PRODUCTION_PROMOTION=/path/to/private-gate/kimi_sandoq_promotion.json KIMI_PRODUCTION_PROMOTION_SHA256=PROMOTION_SHA256 KIMI_PRODUCTION_CONCURRENCY=REQUESTED_CONCURRENCY KIMI_ECR_ROTATION_STATE_FILE=/path/to/private-rotation/state.json sbatch --parsable \$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/run_mobius_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch" C-m
```

The launcher creates a job-specific generation directory and run directory,
copies the two exact-hash deployment source files into a private committed
snapshot, derives the server-scoped direct-worker manifest from that snapshot,
starts the consistent-hash
router, validates the promotion and source tree, and delegates the evaluation
to the provider-context supervisor. It emits aggregate status only.
It probes all 24 direct backends and never routes rollout traffic through the
shared deployment proxy.

## Monitor and finalize

Monitor scheduler state, aggregate result-row counts, pool event counts, router
metrics, rotator heartbeat, and cleanup state. Do not display JSONL rows or raw
exception payloads. A task-level error is retained for coverage and excluded
from SFT; infrastructure or certificate failures remain fail-closed.

After the source job is terminal and the login-side rotator has been stopped,
submit the server-scoped finalizer with the exact launch certificate, run
directory, rotator event log, a fresh mode-0700 SFT root, and a pinned tokenizer
snapshot:

```text
configs/eval/servers/cpu-132-021_8103/finalize_mobius_kimi_k3_sandoq_cpu-132-021_8103.sbatch
```

The finalizer accepts the source job only when scheduler accounting is terminal
and quiescent. It then binds the rotation audit, full 2,499-task coverage,
router/capacity evidence, verified cleanup, exact source and input hashes, and
positive-trace trainability into a trace certificate. Finally it performs a
pass-only export with exact provider JSON required and publishes the standard
tokenizer/rendering preflight attestation. A partial or failed finalization is
never resumed into an existing output namespace.
