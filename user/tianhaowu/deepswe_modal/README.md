# Nemotron Super on DeepSWE with Modal

This launch uses Pier 0.3.1, mini-swe-agent 2.2.8, and Modal sandboxes against
the four-node Nemotron Super inference deployment. The CPU driver creates an
authenticated, temporary Modal relay to the private inference router; it does
not use Prime Sandbox or require a Prime API key.

The relay sandbox exposes encrypted Modal ports, so it must retain Modal's
default network mode. Access to the inference endpoint is still gated by a
random bearer token enforced by the CPU-side Caddy proxy.

Modal's SDK cannot reach its API from the login node on this cluster. Submit
the driver to the CPU partition, where a real Modal sandbox launch has been
verified.

## TOML launcher

Edit the inference job ID and eval settings in
`nemotron_super_deepswe.toml`, then submit one CPU driver job:

```bash
sbatch user/tianhaowu/deepswe_modal/submit_eval.sbatch \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe.toml
```

Use `nemotron_super_deepswe_smoke.toml` for the one-task smoke. The launcher
validates the TOML, renders a Pier JSON config under
`/checkpoint/ram/tianhaowu/deepswe_eval/configs/`, creates the authenticated
Modal relay, runs the thinking preflight, and then starts Pier. The sbatch
template explicitly requests `--partition=cpu`; only the separate inference
job uses H200 nodes.

Validate a TOML without launching an eval:

```bash
uv run --no-sync python user/tianhaowu/deepswe_modal/submit_eval.py \
  user/tianhaowu/deepswe_modal/nemotron_super_deepswe.toml \
  --dry-run
```

## Thinking preservation

Nemotron inference uses the `nemotron_v3` reasoning parser, and every eval
request sets `enable_thinking=true`. Its Hugging Face chat template preserves
historical reasoning with `truncate_history_thinking=false`. The similarly
named `preserve_all_thinking` setting belongs to other renderers and is not a
variable in this deployed template.

Before Pier starts, `verify_mini_swe_thinking.py` runs three real turns through
mini-swe-agent 2.2.8 and LiteLLM. It records every outgoing request and model
completion, verifies that turn 3 forwards the exact reasoning from turns 1 and
2, and checks the live vLLM `/tokenize` plus `/detokenize` result contains both
reasoning blocks. The proof is stored as `thinking_preflight.json` in the
driver job directory. The eval fails closed if any check fails.

CPU jobs inherit an HTTP proxy. Pier's Modal client must run with
`MODAL_DISABLE_API_PROXY=1`; direct Modal API connectivity from CPU nodes is
verified, while the injected proxy requires an optional SOCKS dependency and
breaks sandbox creation.

Pier can leave its tool process alive after writing a finished `result.json`.
The launchers use `pier_runner.py` to detect that durable terminal state,
terminate the lingering process group, and reject jobs with incomplete trials
or infrastructure exceptions.

The Pier wheel set is warmed into the shared uv cache before submission. CPU
drivers invoke `uv tool run --offline` so transient compute-node PyPI proxy
failures cannot prevent an evaluation from starting.

Validate every reference solution and verifier before the model-wide run:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR sbatch \
  user/tianhaowu/deepswe_modal/run_deepswe_oracle.sbatch \
  user/tianhaowu/deepswe_modal/deepswe_oracle_modal_full.yaml \
  deepswe-v1.1-oracle
```

The oracle launcher exits nonzero unless all 113 tasks are present, have no
trial exception, and report `reward=1`; use its successful completion as an
`afterok` dependency for the full model evaluation. The validator reads Pier
0.3.1's per-trial `result.json` files as well as aggregate results that embed
trial records.

Smoke:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR sbatch \
  user/tianhaowu/deepswe_modal/run_deepswe_modal.sbatch \
  user/tianhaowu/deepswe_modal/deepswe_nemotron_modal_smoke.yaml \
  INFERENCE_JOB_ID \
  nemotron-super-deepswe-smoke
```

Full pass@1 evaluation:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR sbatch \
  user/tianhaowu/deepswe_modal/run_deepswe_modal.sbatch \
  user/tianhaowu/deepswe_modal/deepswe_nemotron_modal_full.yaml \
  INFERENCE_JOB_ID \
  nemotron-super-deepswe-pass1
```

Pier results are stored under
`/checkpoint/ram/tianhaowu/deepswe_eval/jobs/`. Driver, relay, Caddy, and SSH
logs are stored under `/checkpoint/ram/tianhaowu/deepswe_eval/driver/` and in
the corresponding `driver_JOB_ID.log` file.
