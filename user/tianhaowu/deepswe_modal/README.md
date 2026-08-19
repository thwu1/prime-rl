# Nemotron Super DeepSWE sandbox evaluation

This workflow runs Pier 0.3.1 and mini-swe-agent 2.2.8 against the private,
four-node Nemotron Super inference deployment. The evaluator and every launcher
run on a CPU Slurm node. The inference server is the only GPU job.

The sandbox provider is selected independently from inference:

- `modal` uses Pier's native Modal environment.
- `vmvm` uses `VMVMRuntime`, backed by a `vacli` lease and `vmvm_tb_v2`.
- `sandoq` uses `SandoqRuntime` and the pinned provider from PR 17 in
  `deps/sandoq-provider`.

VMVM and Sandoq implement the same Verifiers v1 `Runtime` contract as Modal:
provision, foreground/background execution, binary reads and writes, host
inference reachability, and cleanup. Pier's adapter also materializes the
DeepSWE verifier Dockerfiles (`FROM`, file `COPY`, and `RUN`) inside a separate
runtime, keeping hidden tests out of the agent sandbox.
For VMVM and Sandoq, the adapter stages the CPU evaluator's local `uv` binary
before installing MiniSWE. This avoids a GitHub release download in every
ephemeral sandbox and the resulting shared-egress HTTP 429 failures.

The CPU driver publishes the private inference router through a temporary,
authenticated Modal relay. Modal is therefore required for the relay even when
the task sandbox provider is VMVM or Sandoq. Task sandboxes never use Prime
Sandbox. Sandoq defaults to a temporary Modal reverse relay for the Verifiers
host-interception endpoint, so it does not require `PRIME_API_KEY`; set
`host_tunnel = "prime"` explicitly only when that behavior is desired.

## TOML launcher

Set the inference job and provider in the TOML:

```toml
name = "nemotron-super-deepswe-smoke"
inference_job_id = "10689059"
provider = "vmvm" # modal, vmvm, or sandoq

[thinking]
enabled = true
preserve_previous = true
```

To run an exact subset, set task directory names rather than Pier's generated
trial IDs:

```toml
task_names = [
  "fastapi-implicit-head-options",
]
```

Provider-specific runtime fields can be supplied in `[provider_options]`.
For example, the DeepSWE Sandoq configuration is:

```toml
[provider_options]
mode = "oci-runner"
host_tunnel = "modal"
```

Submit the CPU driver with:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe_smoke.toml
```

The CLI can override the TOML provider without editing the file:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe_smoke.toml \
  --provider vmvm
```

Render and validate without launching:

```bash
uv run --no-sync python user/tianhaowu/deepswe_modal/submit_eval.py \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe.toml \
  --provider modal --dry-run
```

Generated Pier configs live under
`/checkpoint/ram/tianhaowu/deepswe_eval/configs/`; results live under
`/checkpoint/ram/tianhaowu/deepswe_eval/jobs/`.

When a completed run needs an exact subset recovery, merge only after the
recovery is terminal and fully scored:

```bash
uv run --no-sync python user/tianhaowu/deepswe_modal/merge_recovered_results.py \
  --base /checkpoint/path/to/original-job \
  --recovery /checkpoint/path/to/recovery-job \
  --tasks /checkpoint/ram/tianhaowu/deepswe_eval/deep-swe/tasks \
  --replace-task fastapi-implicit-head-options \
  --output /checkpoint/path/to/combined-result.json
```

The merge fails unless the final set has one scored result for every benchmark
task and every recovery replacement is exception-free. Scored base outcomes
such as an agent timeout followed by successful verification are preserved and
recorded by exception type. The output includes the source path and SHA-256 of
every selected result.

## Thinking preservation

Every request sets `enable_thinking=true` and
`truncate_history_thinking=false`. Before Pier starts,
`verify_mini_swe_thinking.py` performs three live mini-swe turns, records every
outgoing request and completion, verifies both prior reasoning blocks are
forwarded unchanged, then checks vLLM's live chat-render endpoint contains both
blocks and produces the same prompt-token count as the actual third completion.
Malformed stochastic tool calls are retried with a different seed; the
reasoning and renderer checks still fail closed.

LiteLLM emits prior assistant thinking as `reasoning_content`, while the
inference router forwards the canonical `reasoning` field. The eval relay
normalizes that alias before every chat request reaches the router. Without
this boundary normalization, the request history can look complete in the
MiniSWE trajectory while the worker receives a prompt with prior thinking
removed.

The relay also sets a stable `X-Correlation-ID` derived from the task prompt.
The inference router's consistent-hash policy therefore keeps every turn of one
trajectory on the same replica for prefix-cache reuse while distributing
different DeepSWE tasks across all inference replicas.

The proof is written to:

```text
/checkpoint/ram/tianhaowu/deepswe_eval/driver/JOB_ID/thinking_preflight.json
```

The relay also audits every real eval request, verifies that the prior reasoning
hash sequence is preserved exactly from one turn to the next, renders each
task's latest request through `/v1/chat/completions/render`, and requires its
token count to equal the prompt-token usage reported by the actual completion.
See `request_capture.jsonl`, `latest_requests/`, and
`thinking_trajectory_audit.json` in the same directory.
The driver runs this audit after every terminal Pier aggregate, including runs
with benchmark-level errored trials. Errors remain part of the score/result;
they do not suppress the independent thinking-preservation audit.
To rerun only the audit for an existing completed driver directory on a CPU
node:

```bash
sbatch user/tianhaowu/deepswe_modal/audit_capture.sbatch \
  /checkpoint/ram/tianhaowu/deepswe_eval/driver/JOB_ID INFERENCE_JOB_ID
```

The capture proxy selects `latest_requests/` by per-task request sequence, not
response completion order. A slow older completion therefore cannot overwrite
a newer request snapshot. For a run produced before that guard, reconstruct the
single stale snapshot from the saved MiniSWE trajectory, then audit the copied
request set on a CPU node:

```bash
uv run --no-sync python user/tianhaowu/deepswe_modal/recover_latest_request.py \
  /checkpoint/ram/tianhaowu/deepswe_eval/driver/JOB_ID TASK_KEY TRAJECTORY.json
sbatch user/tianhaowu/deepswe_modal/audit_capture.sbatch \
  /checkpoint/ram/tianhaowu/deepswe_eval/driver/JOB_ID INFERENCE_JOB_ID \
  --latest-dir /checkpoint/ram/tianhaowu/deepswe_eval/driver/JOB_ID/recovered_latest_requests \
  --output /checkpoint/ram/tianhaowu/deepswe_eval/driver/JOB_ID/thinking_trajectory_audit_recovered.json
```

Recovery fails unless the stale request is an exact prefix of the trajectory
and its message count matches a successful request summary. The provenance file
records both request sequence numbers and all relevant SHA-256 hashes.

When Pier retries a task, the first two-message request is recorded as a new
attempt and starts a fresh prefix chain. Reasoning preservation still fails
closed within every attempt; a valid retry is not compared against the failed
attempt's history.

DeepSWE grades the committed `base..HEAD` diff. The custom Pier MiniSWE adapter
therefore stages all remaining changes and creates a no-hook submission commit
after the agent exits. It records the before/after revisions and final clean
status in `agent/submission-commit.txt`; a dirty worktree fails the trial instead
of silently producing an empty patch.

A diagnostic `step_limit` may make MiniSWE return nonzero after saving its
trajectory. Capped diagnostics select MiniSWE's non-interactive default agent so
the limit produces an authoritative `LimitsExceeded` exit instead of asking for
a new limit on stdin. The adapter accepts `Submitted`, `LimitsExceeded`, or an
explicit native context-window exhaustion. It records either limit in
`agent/submission-exit.txt`, then commits and verifies the accumulated solution.
Every other exit still fails the trial. Context-window 400s are listed in the
thinking audit as `context_limit_events`; the audit renders the last successful
request and still fails on every unrelated HTTP or reasoning-history error.

Full evaluations can bound MiniSWE turns and agent wall time directly in TOML:

```toml
sandbox_timeout_sec = 14400
sandbox_startup_timeout_sec = 3600
verifier_timeout_multiplier = 4.0

[mini_swe]
step_limit = 200
timeout_sec = 10800
```

`timeout_sec` configures Pier's agent deadline. `sandbox_timeout_sec` raises the
VMVM/Sandoq command-transport ceiling above the agent deadline, leaving time for
transport latency, collection, and verification commands. VMVM and
Sandoq leases auto-renew while their runtimes are active, so their short renewal
TTLs do not cap trial duration.
`verifier_timeout_multiplier` scales each task's declared verifier deadline.
Remote VMVM/Sandoq execution can be slower than local Docker; the checked-in
full eval uses `4.0` so a slow but progressing verifier is not misclassified as
an infrastructure failure.
`sandbox_startup_timeout_sec` separately bounds VMVM image pulls and Sandoq OCI
image/bootstrap setup; one hour leaves startup headroom without turning a stuck
pull into a multi-hour trial.

The MiniSWE instance template uses fixed `Linux x86_64` system information.
Provider-specific kernel strings otherwise change the prompt before the first
model turn and invalidate fixed-seed Modal/VMVM/Sandoq trajectory comparisons.

The inference deployment must use the `nemotron_v3` reasoning parser and an
automatic tool-call parser. Its configured context limit is 262,144 tokens;
the DeepSWE request limit is 32,768 output tokens.

## Oracle gates

Run the reference solution through the selected provider:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch modal
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch vmvm --n-concurrent 8 \
  --verifier-timeout-multiplier 4
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch sandoq --n-concurrent 8 \
  --verifier-timeout-multiplier 4
```

For a targeted provider smoke:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch vmvm \
  --n-concurrent 1 \
  --task-name httpx-multipart-response-parsing \
  --name deepswe-v1.1-oracle-httpx
```

The full validator requires exactly 113 unique tasks, no exceptions, and
`reward=1` for every task. A sampled oracle uses `--n-tasks` or `--task-name`
and validates the selected count against the same task set.

## Sandoq setup

Install the PR-pinned official client into the shared read-only target once:

```bash
sbatch user/tianhaowu/deepswe_modal/setup_sandoq_client.sbatch
```

DeepSWE needs Sandoq's OCI-runner mode because every task has a distinct image.
It requires a regular mode-`0600` bearer-token file at:

```text
/home/tianhaowu/.config/oci-runner/token
```

The CPU nodes can reach the Sandoq gateway directly with mTLS, but their
inherited proxy is not usable. `provider_environment_context` runs a loopback
CONNECT tunnel and points the official client at it; the installed client and
its authentication logic remain unchanged.

Sandoq's PR-17 provider leaves agent-inside reverse tunneling unimplemented.
`SandoqRuntime.host_endpoint()` supplies that missing Runtime operation with a
temporary Modal SSH relay by default. This is separate from the Sandoq task
sandbox and does not use Prime Sandbox or Prime tunnel credentials.

Validate the provider contract independently:

```bash
sbatch user/tianhaowu/deepswe_sandoq/run_runtime_smoke.sbatch environment
sbatch user/tianhaowu/deepswe_sandoq/run_runtime_smoke.sbatch oci-runner
```

## Trajectory parity

Use the dedicated parity TOML so every provider receives the same task and the
same fixed vLLM request seed:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe_parity.toml \
  --provider modal
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe_parity.toml \
  --provider vmvm
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe_parity.toml \
  --provider sandoq
```

The comparator rejects mismatched agent/model sampling configs before comparing
commands. This diagnostic config also applies the same 100-step mini-swe cap on
every provider; the score configs remain governed only by each task's 90-minute
agent timeout. The fixed seed reduces sampling variance, but vLLM may still
produce harmless byte-level differences such as a trailing newline or a
generated tool-call ID. Compare sandbox behavior rather than requiring the raw
completions to be byte-identical.

Compare completed jobs by task name:

```bash
uv run --no-sync python \
  user/tianhaowu/deepswe_modal/compare_provider_trajectories.py \
  modal=/checkpoint/ram/tianhaowu/deepswe_eval/jobs/MODAL_JOB \
  vmvm=/checkpoint/ram/tianhaowu/deepswe_eval/jobs/VMVM_JOB \
  sandoq=/checkpoint/ram/tianhaowu/deepswe_eval/jobs/SANDOQ_JOB \
  --output /checkpoint/ram/tianhaowu/deepswe_eval/provider-parity.json
```

The report checks task checksum and prompt equality, provider exceptions,
reasoning coverage, normalized and exact per-turn reasoning hashes, reward and
patch hashes, aligned command return codes and outputs, command-sequence
similarity, timings, and agent-issued network commands. Prompt/config identity,
complete reasoning, command outcomes, and verifier behavior are the parity
signals. Exact reasoning hashes remain diagnostic for byte-level drift.

VMVM and Sandoq keep provider networking enabled so the in-sandbox agent can
reach the authenticated model relay. Non-agent verifier commands explicitly
clear inherited proxy variables, and the trajectory report surfaces any network
commands issued by the agent.
