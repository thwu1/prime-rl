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
a new limit on stdin. The adapter accepts only `Submitted` or
`LimitsExceeded`, records the latter in `agent/submission-exit.txt`, then commits
and verifies the accumulated solution. Every other exit still fails the trial.

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
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch vmvm --n-concurrent 8
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch sandoq --n-concurrent 8
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
