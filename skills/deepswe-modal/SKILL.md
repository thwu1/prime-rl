---
name: deepswe-modal
description: Launch and validate DeepSWE evaluations with mini-swe-agent, Modal sandboxes, and a private prime-rl inference job. Use for the Nemotron DeepSWE CPU launcher, oracle gate, Modal relay, or thinking-preservation checks.
---

# DeepSWE with Modal

The workflow lives in `user/tianhaowu/deepswe_modal/`. The inference server is
a separate GPU job; all oracle, smoke, full-eval, relay, and validation drivers
must run on the CPU partition.

## Launch from TOML

Edit `nemotron_super_deepswe.toml` and submit:

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

The sbatch template requests `partition=cpu`, renders a Pier JSON config, and
runs `run_deepswe_modal.py`. Pier is invoked offline because compute-node PyPI
proxy access is unreliable. Set `MODAL_DISABLE_API_PROXY=1` for Modal SDK calls
from CPU nodes.

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
Inspect:

```text
/checkpoint/ram/tianhaowu/deepswe_eval/driver/JOB_ID/thinking_preflight.json
```

The inference job must expose the model through the `nemotron_v3` reasoning
parser and an automatic tool-call parser. Confirm in the resolved inference
config and runtime log before evaluating.

## Oracle gate

Run all reference solutions before the full eval. `validate_oracle.py` supports
Pier 0.3.1's aggregate job result plus its per-trial `*/result.json` files. A
valid DeepSWE v1.1 oracle run has exactly 113 trials, no exceptions, no missing
tasks, and reward 1 for every task.

Use the successful oracle gate and smoke job as `afterok` dependencies for the
full TOML submission.
