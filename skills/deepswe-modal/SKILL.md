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
The runtime adapter stages the CPU evaluator's local `uv` binary before
installing MiniSWE. Do not restore the per-sandbox Astral/GitHub installer; the
shared provider egress can return HTTP 429 under even small concurrent runs.

The sbatch template requests `partition=cpu`, renders a Pier JSON config, and
runs `run_deepswe_modal.py`. Pier is invoked offline because compute-node PyPI
proxy access is unreliable. The driver always uses a temporary authenticated
Modal relay for the private inference router, independent of the task sandbox
provider. Set `MODAL_DISABLE_API_PROXY=1` for Modal SDK calls from CPU nodes.

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
unchanged, then verifies the live vLLM-rendered turn-3 prompt contains both.
Malformed stochastic tool calls may retry with a new seed; reasoning and render
validation still fail closed.
The eval relay also records a compact line for every actual model request,
checks that the prior reasoning hash sequence is an exact prefix of the next
turn, retains each task's latest exact request, and renders those final requests
through the live vLLM tokenizer. Inspect `request_capture.jsonl`,
`latest_requests/`, and `thinking_trajectory_audit.json` in the driver job
directory.

DeepSWE collects the committed `base..HEAD` diff, while MiniSWE's completion
marker only exits the agent. The Pier agent adapter stages any remaining changes,
creates a no-hook submission commit, and requires a clean worktree before the
verifier runs. Inspect `agent/submission-commit.txt`; do not treat a staged-only
working tree as a submitted solution.
For capped diagnostics, a nonzero MiniSWE exit is accepted only when the saved
trajectory explicitly reports `LimitsExceeded`; the adapter records that gate in
`agent/submission-exit.txt` before committing. Other nonzero exits still fail.

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

## Oracle gate

Run all reference solutions before the full eval:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_oracle.sbatch vmvm --n-concurrent 8
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
per-turn reasoning hashes, rewards, patches, aligned command outcomes, timings,
and agent-issued network commands.
