---
name: deepswe-modal
description: Launch and validate DeepSWE evaluations with mini-swe-agent, Modal/VMVM/Sandoq sandboxes, and a private prime-rl inference job. Use for provider selection, oracle gates, trajectory parity, the Modal relay, or thinking-preservation checks.
---

# DeepSWE sandbox providers

The workflow lives in `user/tianhaowu/deepswe_modal/`. The inference server is
a separate GPU job; all oracle, smoke, full-eval, relay, and validation drivers
must run on the CPU partition.

## Launch from TOML

Set `provider = "modal"`, `"vmvm"`, or `"sandoq"` in the TOML and submit:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe.toml
```

For one task, use `nemotron_super_deepswe_smoke.toml`. Validate config rendering
without launching:

```bash
uv run --no-sync python user/tianhaowu/deepswe_modal/submit_eval.py \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe.toml --dry-run
```

Override the TOML selection with `--provider vmvm`. Modal uses Pier's native
environment. VMVM and Sandoq use `PierRuntimeEnvironment`, which adapts the
Verifiers v1 Runtime contract and materializes DeepSWE verifier Dockerfiles in
a separate sandbox so hidden tests never enter the agent sandbox.
These remote runtimes are ephemeral: Pier's temporary `delete=False` during
separate-verifier mode does not retain them, because their task images are
registry-backed and keeping every completed agent sandbox would exhaust provider
capacity.

The checked-in full-eval config uses 32 concurrent trials. The oracle launcher
defaults to 64. Full evals and oracles use up to six whole-trial retries for
transient provider provisioning failures. Both launchers propagate the requested concurrency to
`VACLI_MAX_CONCURRENT_LEASES` or `OCI_RUNNER_POOL_SIZE`, so the runtime pool does
not silently retain its smaller standalone-smoke default.
Set `[mini_swe].step_limit` to bound agent turns and
`[mini_swe].timeout_sec` to bound agent wall time. Set the top-level
`sandbox_timeout_sec` at least as high as the agent timeout, with headroom, for
the VMVM/Sandoq command-transport ceiling. Their leases auto-renew while active.
Use top-level `task_names = ["task-directory-name"]` to recover an exact subset.
These are names under the configured tasks directory, not Pier trial IDs with a
generated `__SUFFIX`.
After the subset finishes, use `merge_recovered_results.py` with one
`--replace-task` per recovered task. It validates the exact benchmark task set,
requires every replacement to be exception-free, preserves base trials that
have verifier metrics after a scored agent timeout, checks task checksums, and
writes per-task paths, exception types, and SHA-256 provenance.
Set `verifier_timeout_multiplier = 4.0` for full VMVM/Sandoq runs so their
slower remote execution can finish each task's verifier without changing the
tests or reward logic.
Set `sandbox_startup_timeout_sec` separately for VMVM image pulls and Sandoq OCI
image/bootstrap setup; the checked-in full eval uses one hour.
Whole-trial retries are restricted to `SandboxError`,
`EnvironmentStartTimeoutError`, and `AgentSetupTimeoutError`. Do not broaden
that allowlist to agent execution, verifier, reward, or parsing failures; those
are evaluation outcomes and rerolling them would resample the model.
The Runtime adapter classifies a failed agent installation command as
`SandboxError`, so transient package-index and mirror failures retry the whole
trial instead of becoming a terminal missing score.
For root setup steps that run `apt-get update`, it temporarily hides third-party
source files and restores them when the setup shell exits. Generic MiniSWE
dependencies come from the base Debian/Ubuntu repositories, so a stale task-
specific package index cannot block agent installation.
The runtime adapter stages the CPU evaluator's local `uv` binary before
installing MiniSWE. Do not restore the per-sandbox Astral/GitHub installer; the
shared provider egress can return HTTP 429 under even small concurrent runs.

The sbatch template requests `partition=cpu`, renders a Pier JSON config, and
runs `run_deepswe_modal.py`. Pier is invoked offline because compute-node PyPI
proxy access is unreliable. The driver starts an authenticated request-capture
proxy on the CPU node and registers it with the shared `ram-inference-gateway`.
The registration is a 15-second heartbeat with a 45-second TTL; cleanup
de-registers it. Agents in Modal, VMVM, or Sandoq call the stable public gateway,
which routes the model name back to the CPU capture proxy and then the private
inference router. This path uses no Modal relay sandbox.

The gateway registry is keyed by model name, so each eval registers a unique
`deepswe-PROVIDER-SLURM_JOB_ID` alias. The CPU capture proxy rewrites that alias
to the actual served model before forwarding to vllm-router. Concurrent
provider evals therefore keep separate capture logs and cannot steal each
other's route.
From a login or CPU node, inspect the gateway through the internal ingress:

```bash
curl --noproxy '*' -H 'Host: ram-inference-gateway.ingress.' \
  http://fair-sc-3-ingress-slurm-ingress/v1/models
```

Set `MODAL_DISABLE_API_PROXY=1` only for actual Modal SDK calls, such as a Modal
task-sandbox run.

## Required Nemotron thinking settings

Use these request-level chat template kwargs:

```toml
[thinking]
enabled = true
preserve_previous = true
```

The TOML launcher renders them to:

```json
{"enable_thinking": true, "truncate_history_thinking": false}
```

`preserve_all_thinking` is not consumed by the deployed Nemotron Hugging Face
chat template. vLLM filters undeclared template kwargs, and Nemotron defaults
`truncate_history_thinking` to true, which removes reasoning before the latest
user turn.

Do not bypass `verify_mini_swe_thinking.py`. It uses mini-swe-agent 2.2.8 and
LiteLLM for three live turns, checks both prior reasoning messages are forwarded
unchanged, then verifies the live chat-rendered turn-3 prompt contains both and
has the same token count as the actual completion request.
Malformed stochastic tool calls may retry with a new seed; reasoning and render
validation still fail closed.
LiteLLM emits prior thinking as `reasoning_content`; the eval relay must
canonicalize it to `reasoning` before the request crosses vllm-router. Logging
the incoming alias is not proof that the backend received it. The final audit
uses `/v1/chat/completions/render` and compares its token count with actual API
usage so router-side field loss fails closed.
The relay must also attach its stable per-task `X-Correlation-ID`. The inference
router's consistent-hash policy otherwise sees an empty chat key and sends every
trajectory to one replica. The correlation header keeps each trajectory sticky
for prefix caching while spreading different tasks across all replicas.
The eval relay also records a compact line for every actual model request,
checks that the prior reasoning hash sequence is an exact prefix of the next
turn, retains each task's latest exact request, and renders those final requests
through the live vLLM chat renderer. Inspect `request_capture.jsonl`,
`latest_requests/`, and `thinking_trajectory_audit.json` in the driver job
directory. Both the summaries and latest requests are checkpoint-backed, and a
Slurm-requeued CPU driver restores its request counters, attempts, and latest
reasoning hashes before resuming Pier. Do not move capture state back to local
`/tmp`; a node requeue would make the final audit incomplete.
Run this audit for every terminal Pier aggregate. Benchmark-level errored trials
are valid scored outcomes and must not suppress the independent thinking audit;
only an unfinished, running, pending, or cancelled aggregate blocks it.
Rerun only this audit for an existing completed driver directory on a CPU node
with:

```bash
sbatch user/tianhaowu/deepswe_modal/audit_capture.sbatch \
  /checkpoint/ram/tianhaowu/deepswe_eval/driver/JOB_ID INFERENCE_JOB_ID
```

The capture proxy must update `latest_requests/` by `per_task_request`, not by
response completion order; concurrent older requests can finish after newer
ones. For a historical run with one stale snapshot, use
`recover_latest_request.py` to reconstruct it from the saved MiniSWE trajectory.
The tool requires the stale capture to be an exact trajectory prefix and emits
hash provenance. Pass its copied directory to `audit_capture.sbatch` with
`--latest-dir` and write a separate report with `--output`.

Pier retries start a new prefix chain only when the capture sees an explicit
two-message request with no prior reasoning after a nonempty attempt. The
summary records `attempt`, `per_attempt_request`, and `retry_boundary`; do not
treat a legitimate retry as missing historical reasoning from its failed
predecessor.

DeepSWE collects the committed `base..HEAD` diff, while MiniSWE's completion
marker only exits the agent. The Pier agent adapter stages any remaining changes,
creates a no-hook submission commit, and requires a clean worktree before the
verifier runs. Inspect `agent/submission-commit.txt`; do not treat a staged-only
working tree as a submitted solution.
For capped diagnostics, a nonzero MiniSWE exit is accepted only when the saved
trajectory explicitly reports `LimitsExceeded`; capped configs use MiniSWE's
non-interactive default agent so reaching the limit never prompts for replacement
limits on stdin. The adapter records that gate in `agent/submission-exit.txt`
before committing. Other exit states still fail.

Use the checked-in provider-neutral MiniSWE instance template. The upstream
template embeds each sandbox's kernel string, making the Modal and VMVM prompts
different before turn one and invalidating deterministic trajectory parity.

Inspect:

```text
/checkpoint/ram/tianhaowu/deepswe_eval/driver/JOB_ID/thinking_preflight.json
```

The inference job must expose the model through the `nemotron_v3` reasoning
parser and an automatic tool-call parser. Confirm in the resolved inference
config and runtime log before evaluating.

Full-history thinking makes the inference context limit part of eval validity.
Nemotron Super declares `max_position_embeddings = 262144`; use that native
limit for unlimited-step DeepSWE scoring. A server capped at 102144 rejects the
next turn once the preserved prompt reaches 102145 tokens, causing mini-swe to
exit nonzero and the trial to score zero even when P2P is otherwise perfect.
The 100-step parity diagnostic may use less context, but do not treat a 102144
full eval as valid merely because the thinking preflight passes.
At the native boundary, the next preserved prompt may itself render above
262144. The agent adapter accepts only the explicit context-window error as a
terminal limit, records `accepted_exit_status=ContextWindowExceeded`, and
commits the current patch. The capture audit records those 400 responses under
`context_limit_events` and renders the last successful request; it still fails
on every other HTTP error or any missing/reordered reasoning.

## Oracle gate

Run all reference solutions before the full eval:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch vmvm \
  --n-concurrent 64 --max-retries 6 \
  --sandbox-timeout-sec 14400 --verifier-timeout-multiplier 4
```

`validate_oracle.py` supports
Pier 0.3.1's aggregate job result plus its per-trial `*/result.json` files. A
valid DeepSWE v1.1 oracle run has exactly 113 trials, no exceptions, no missing
tasks, and reward 1 for every task.

Use the successful oracle gate and smoke job as `afterok` dependencies for the
full TOML submission.

## Provider parity

Launch every backend from `nemotron_super_deepswe_parity.toml`. It selects the
same task, sets a fixed request seed, and applies the same 100-step diagnostic
cap; do not compare independently sampled temperature-1 runs as evidence of
sandbox parity. A fixed seed reduces variance but does not guarantee
byte-identical vLLM output; use prompt/config identity, normalized reasoning,
commands and outcomes, rewards, and patches as behavior signals. Treat exact
reasoning hashes as a diagnostic. The score TOMLs intentionally keep mini-swe's
unlimited step setting and rely on the task's 90-minute agent timeout.

After matched jobs finish, compare their ATIF trajectories:

```bash
uv run --no-sync python user/tianhaowu/deepswe_modal/compare_provider_trajectories.py \
  modal=/path/to/modal-job vmvm=/path/to/vmvm-job sandoq=/path/to/sandoq-job \
  --output /path/to/provider-parity.json
```

The report first checks the normalized agent/model sampling config, then checks
prompt/task identity, exceptions, reasoning coverage, normalized and exact
per-turn reasoning hashes, rewards, patches, aligned command outcomes, their
common prefix and first divergence, timings, and agent-issued network commands.
