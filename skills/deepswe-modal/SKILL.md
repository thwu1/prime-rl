---
name: deepswe-modal
description: Launch and validate DeepSWE evaluations with mini-swe-agent, Modal/VMVM/Sandoq sandboxes, and a private prime-rl inference job. Use for provider selection, oracle gates, trajectory parity, the RAM inference gateway, or thinking-preservation checks.
---

# DeepSWE sandbox providers

The workflow lives in `user/tianhaowu/deepswe_modal/`. The inference server is
a separate GPU job; all oracle, smoke, full-eval, gateway, and validation
drivers must run on the CPU partition.

The standalone OpenHands SDK alternative lives in
`user/tianhaowu/deepswe_openhands/`. Do not add OpenHands conditionals to the
MiniSWE launcher. Its own sbatch launcher, TOML renderer, Pier agent, prompt,
runner, ATIF conversion, and logs are isolated there; it reuses only the stable
provider/runtime and request-capture boundaries.

Run its VMVM smoke before a full evaluation:

```bash
sbatch user/tianhaowu/deepswe_openhands/submit_eval.sbatch \
  user/tianhaowu/deepswe_openhands/nemotron_super_deepswe_vmvm_smoke.toml
sbatch user/tianhaowu/deepswe_openhands/submit_eval.sbatch \
  user/tianhaowu/deepswe_openhands/nemotron_super_deepswe_vmvm.toml
```

OpenHands is pinned inside the task sandbox, uses TerminalTool plus
FileEditorTool, disables condensation, and defaults to 200 iterations with a
three-hour Pier timeout. OpenHands 1.42.1 does not classify the private gateway
alias as an interleaved-thinking model, so the runner explicitly enables its
reasoning-history serializer only when `thinking.preserve_previous=true`.
For the no-preserve mode it verifies that the serializer omits a synthetic
prior reasoning message before the first live request. The normal
capture/render audit remains the independent proof for actual requests. Inspect `serializer-contract.json`,
`openhands-events.json`, `openhands-trajectory.json`, and Pier's ATIF
`trajectory.json` in each trial's `agent/` directory.
The no-preserve capture audit requires every outbound prior-assistant reasoning
count and reasoning-alias normalization count to remain zero; preserve mode
retains the stricter exact-prefix invariant.
Its launcher maps `sandbox_startup_timeout_sec` to Pier's environment-build
timeout multiplier in the same way as the MiniSWE launcher.
After OpenHands exhausts its internal LLM retries, its adapter classifies only
explicit API transport/service failures as `SandboxError` for a whole-trial
retry; other nonzero exits remain evaluation outcomes.
Match LiteLLM's wrapped gateway failures as well as HTTP reason phrases; its
`BadGatewayError: Error code: 502 ... Connection refused` wording does not
necessarily contain the literal `502 Bad Gateway` string.

Keep `top_k` in `LLM.litellm_extra_body`, not the SDK's top-level `top_k`
field. OpenHands types the top-level field as a float, while the prime-rl vLLM
endpoint validates `top_k` as an integer and otherwise returns HTTP 422 before
the first model token.

## Launch from TOML

Use the explicit full-eval TOML for the selected provider:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe_modal.toml
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe_vmvm.toml
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe_sandoq.toml
```

The three production configs use concurrency 32, six infrastructure-only
retries, 200 turns, a three-hour agent timeout, a four-hour sandbox/session
ceiling, a one-hour startup ceiling, a 4x verifier timeout, and full-history
thinking. Change only `inference_job_id` for a new inference deployment.

For one task, use `nemotron_super_deepswe_smoke.toml`. Validate config rendering
without launching:

```bash
uv run --no-sync python user/tianhaowu/deepswe_modal/submit_eval.py \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe_vmvm.toml --dry-run
```

For a shared `ram_common/vllm_tools/serve_api_v2` deployment, replace
`inference_job_id` with `upstream_info_path`, point `render_endpoints_path` at
the deployment's direct worker endpoint directory, and set the proxy's sticky
header through `upstream_session_header`. The driver reads the upstream API key
from `proxy_info.json` without copying it into the eval TOML, sends model traffic
through the normal capture/gateway path, and uses a live direct worker only for
the render audit. Kimi-K2.6 requires these thinking kwargs:

```toml
[thinking]
enabled = true
preserve_previous = true

[thinking.template_kwargs]
thinking = true
preserve_thinking = true
```

Use `x-litellm-session-id` as the upstream session header for the shared Kimi
LiteLLM proxy so each task remains sticky to one vLLM replica.

Override the TOML selection with `--provider vmvm`. Modal uses Pier's native
environment. VMVM and Sandoq use `PierRuntimeEnvironment`, which adapts the
Verifiers v1 Runtime contract and materializes DeepSWE verifier Dockerfiles in
a separate sandbox so hidden tests never enter the agent sandbox.
These remote runtimes are ephemeral: Pier's temporary `delete=False` during
separate-verifier mode does not retain them, because their task images are
registry-backed and keeping every completed agent sandbox would exhaust provider
capacity.

The checked-in full-eval configs use 32 concurrent trials. The oracle launcher
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
The launcher also converts this value into Pier's environment-build and agent-
setup timeout multipliers against DeepSWE's 1800-second task default and Pier's
360-second setup default. This prevents an outer Pier watchdog from cancelling
provider startup or package installation before the configured sandbox startup
ceiling is reached.
Whole-trial retries are restricted to `SandboxError`,
`EnvironmentStartTimeoutError`, and `AgentSetupTimeoutError`. Do not broaden
that allowlist to agent execution, verifier, reward, or parsing failures; those
are evaluation outcomes and rerolling them would resample the model.
The DeepSWE MiniSWE adapter inspects a nonzero agent trajectory before applying
that rule. If MiniSWE exhausted its own request retries and the trajectory
explicitly contains a transient API transport/service failure, the adapter
raises `SandboxError` so the rollout can retry. Other nonzero agent exits remain
evaluation outcomes.
For VMVM, the DeepSWE Pier environment first handles command-level connection
drops in place using VMVM-TB-v2's existing `restart_session()` and
`recover_last()` methods. This preserves the same container, filesystem, shell
state, and exactly-once command result without changing either provider's public
Runtime contract. Only failed recovery becomes a whole-trial `SandboxError`.
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

For an explicit default-template ablation, set `preserve_previous = false`.
This keeps current-turn thinking enabled while rendering
`truncate_history_thinking=true`. Use
`nemotron_super_deepswe_vmvm_truncate_history.toml`; its preflight requires both
prior reasoning blocks to be absent from the live turn-3 rendered prompt while
still verifying that MiniSWE forwarded them unchanged. Its terminal audit uses
the same expectation. When rerunning that audit manually, pass
`--truncate-history-thinking` to `audit_capture.sbatch`.

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
reasoning hashes before resuming Pier. An unfinished Pier `result.json` must use
`pier job resume --job-path`; running `pier run` again with the same job name does
not recover its pending trials. Shared `serve_api_v2` deployments validate the
model through a direct render worker because a saturated LiteLLM proxy can keep
serving chat completions while its `/v1/models` and health handlers are blocked.
The live MiniSWE thinking preflight remains the end-to-end proxy readiness gate.
Do not move capture state back to local `/tmp`; a node requeue would make the
final audit incomplete.
After a terminal Slurm node failure, confirm that no writer remains and resume
the existing Pier directory from a fresh CPU allocation with:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch CONFIG.toml \
  --resume-job-id ORIGINAL_SLURM_JOB_ID
```

This re-registers the original gateway model alias and uses the saved
`config.json`, allowing Pier to retain completed trials and rerun only missing
ones. It refuses active source allocations and already-terminal Pier jobs.
Pier deletes a result-less trial directory before recreating that missing trial.
Copy any partial trajectory, submission record, and patch to a separate
provenance directory before submitting the resume if those interrupted
artifacts must be retained for diagnosis.
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
limit for long-horizon DeepSWE scoring. A server capped at 102144 rejects the
next turn once the preserved prompt reaches 102145 tokens, causing mini-swe to
exit nonzero and the trial to score zero even when P2P is otherwise perfect.
The 100-step parity diagnostic may use less context, but do not treat a 102144
full eval as valid merely because the thinking preflight passes.
At the native boundary, the next preserved prompt may itself render above
262144. The agent adapter accepts only the explicit context-window error as a
terminal limit, records `accepted_exit_status=ContextWindowExceeded`, and
commits the current patch. The capture audit records those 400 responses under
`context_limit_events` and renders the last successful request; it still fails
on every other HTTP error or any missing/reordered reasoning. Recognize both
direct-vLLM wording (`exceeds the model's maximum context length`) and LiteLLM's
wrapped wording (`maximum context length is ... requested ...`) when validating
that terminal condition.

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
reasoning hashes as a diagnostic. The score TOMLs use the common 200-step cap
and three-hour agent timeout.

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
