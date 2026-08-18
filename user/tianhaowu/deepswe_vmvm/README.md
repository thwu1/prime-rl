# SWE-bench mini-swe-agent on VMVM

This setup evaluates coding models on SWE-bench Verified with Verifiers v1,
mini-swe-agent, and the vacli-backed VMVM runtime. It does not create Prime
sandboxes. VMVM routes model requests from the remote container to the evaluator's
interception server through the vacli lease's SSH connection, so it does not
require Prime tunnel credentials. The mini-swe-agent benchmark preset uses its
local environment because VMVM already runs the agent inside the SWE-bench task
image.

All launchers pin the existing
`/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft` environment and run with
`UV_NO_SYNC=1`. Treat that environment as read-only: do not run `uv sync` or
install packages into it while the Nemotron SFT job is active. For the manual
render commands below, use the same environment explicitly:

```bash
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
```

The runtime uses a 60-second lease TTL with vacli auto-renewal. Active tasks remain
leased, while a VM is reclaimed quickly if graceful shutdown cannot reach the
control plane.

## Runtime smoke

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch user/tianhaowu/deepswe_vmvm/run_runtime_smoke.sbatch
```

The smoke provisions a VMVM container, runs a command in its task workdir, uploads
and downloads binary data, verifies the digest, reaches a host-local HTTP server
through the VMVM reverse tunnel, and releases the lease.

## Start DeepSWE

Render and validate the inference job before submission:

```bash
uv run --no-sync inference @ user/tianhaowu/deepswe_vmvm/inference.toml --dry-run
bash -n /checkpoint/ram/tianhaowu/deepswe_vmvm/inference/inference.sbatch
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --qos=h100_lowest --no-requeue \
  /checkpoint/ram/tianhaowu/deepswe_vmvm/inference/inference.sbatch
```

Read `INFER_URLS` from the inference job log and wait for `/v1/models` to return
HTTP 200.

## DeepSWE smoke

`smoke.toml` selects one task and runs it at concurrency one:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --export=ALL,INFERENCE_BASE_URL=http://HOST:8000/v1,EVAL_OVERLAY=user/tianhaowu/deepswe_vmvm/smoke.toml \
  user/tianhaowu/deepswe_vmvm/run_eval.sbatch
```

## Full mini-swe-agent evaluation

After the smoke produces a valid patch and score, omit the overlay. The base config
runs all 500 tasks with at most 16 VMVM leases in flight:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --export=ALL,INFERENCE_BASE_URL=http://HOST:8000/v1 \
  user/tianhaowu/deepswe_vmvm/run_eval.sbatch
```

DeepSWE's published 42.2% pass@1 used R2E-Gym, its four-tool prompt, and an average
over 16 runs. The 59.0% number is hybrid Best@16. A mini-swe-agent score validates
the VMVM integration but is not an exact reproduction of either published protocol.

## Reproduce the published mini-swe-agent baseline

The comparable public baseline is
[`20251209_mini-v1.17.2_devstral-small-2512`](https://github.com/SWE-bench/experiments/tree/main/evaluation/bash-only/20251209_mini-v1.17.2_devstral-small-2512):
56.4% resolved on all 500 SWE-bench Verified tasks, one attempt per task, with an
average of 86.866 model calls. The configs here pin the same model,
mini-swe-agent 1.17.2 `swebench.yaml` prompt, 250-step limit, and temperature 0.
The local vLLM run also caps each response at 4,096 tokens. Without that guard,
rare non-terminating responses can fill the KV cache while LiteLLM retries the
same calls. This is above the longest normal response observed during validation
(2,363 tokens) and does not cap the number of agent steps.

The completed VMVM verification scored 275/500 (55.0%), versus the published
282/500 (56.4%): seven tasks and 1.4 percentage points apart. The two runs agreed
on 387 task outcomes; VMVM averaged 77.004 model calls versus 86.866 published.
The zero-error, 500-task artifact is
`/checkpoint/ram/tianhaowu/deepswe_vmvm/evals/run_10596424/results_corrected.jsonl`
with SHA-256
`edb1c750461d8a3be4861b6aa92deefda7980377132c66ec73bf4945caea1afd`.

Render and submit the two-GPU Devstral server:

```bash
uv run --no-sync inference @ user/tianhaowu/deepswe_vmvm/devstral_inference.toml --dry-run
bash -n /checkpoint/ram/tianhaowu/deepswe_vmvm/devstral_inference/inference.sbatch
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --qos=h100_lowest --no-requeue \
  /checkpoint/ram/tianhaowu/deepswe_vmvm/devstral_inference/inference.sbatch
```

After `/v1/models` is ready, first run `django__django-16569`. The published run
resolved this task in 23 API calls:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --export=ALL,INFERENCE_BASE_URL=http://HOST:8000/v1,\
EVAL_CONFIG=user/tianhaowu/deepswe_vmvm/devstral_eval.toml,\
EVAL_OVERLAY=user/tianhaowu/deepswe_vmvm/devstral_smoke.toml \
  user/tianhaowu/deepswe_vmvm/run_eval.sbatch
```

Then run the complete 500-task comparison without `EVAL_OVERLAY`:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --export=ALL,INFERENCE_BASE_URL=http://HOST:8000/v1,\
EVAL_CONFIG=user/tianhaowu/deepswe_vmvm/devstral_eval.toml \
  user/tianhaowu/deepswe_vmvm/run_eval.sbatch
```

mini-swe-agent 1.x only accepts one `-c` config file. The Verifiers harness merges
the built-in versioned preset and all overrides into one temporary YAML before it
starts the agent, which keeps this run compatible with the published 1.17.2 CLI.
Environment-map values must remain strings: quote numeric-looking values inside an
override (for example `env.env.TQDM_DISABLE=\"1\"`).

The in-container local environment executes actions through `bash -lc`, matching
mini-swe-agent's official SWE-bench Docker runner rather than Python's default
`/bin/sh -c` behavior.

Keep `HarnessError` in `retries.rollout.include`. Each isolated VM resolves the
pinned mini-swe-agent script before launch, and a transient package-index or `uv`
failure should restart that task on a fresh VM rather than leave an unscored row.
