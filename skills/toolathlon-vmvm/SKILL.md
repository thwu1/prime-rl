---
name: toolathlon-vmvm
description: Launch, resume, monitor, and audit Toolathlon and Toolathlon-Verified evaluations on VMVM. Use for official Kimi K2.6 leaderboard reproduction, the 108-task internal harness, Nemotron Super base or SFT checkpoint comparisons, multi-replica consistent-hash routing, retry classification, score aggregation, or auditing the 16-used-versus-17-registered local-tool distinction.
---

# Toolathlon on VMVM

The standalone workflow lives in `user/tianhaowu/toolathlon_vmvm/`. Run all
evaluation drivers on the CPU partition. Nemotron inference is a separate GPU
job; the public Kimi path uses the shared endpoint recorded in its TOML.

For lower-level VMVM transport and tunnel behavior, also follow
`skills/vmvm-runtime/SKILL.md`. Read the workflow README before changing a
benchmark contract:

```bash
sed -n '1,260p' user/tianhaowu/toolathlon_vmvm/README.md
```

## Keep the tree lean

Keep only the supported public Kimi, internal Kimi, Nemotron base, Nemotron SFT,
and historical diagnostic configurations. Do not commit result files,
generated inference configs, repair configs, temporary scripts, or superseded
experiment variants. Evaluation output belongs under
`/checkpoint/ram/tianhaowu/toolathlon_vmvm/`, never in the source tree.

## Benchmark choice

Use the official public-service path when comparing Kimi K2.6 directly with the
Toolathlon-Verified leaderboard:

```bash
uv run --no-sync python user/tianhaowu/toolathlon_vmvm/legacy_eval.py \
  user/tianhaowu/toolathlon_vmvm/kimi_k26_verified_v2.toml --dry-run
sbatch user/tianhaowu/toolathlon_vmvm/run_verified_eval.sbatch
```

This is three trials of all 108 tasks with the service-enforced concurrency of
10. The persisted service job ID makes resume exact: rerun the same batch script
and output directory after a CPU-node or VMVM failure. Never delete
`trial_NNN/service_state.json` or resubmit an existing service job manually.

Use the internal VMVM harness for high-concurrency model comparisons:

```bash
sbatch user/tianhaowu/toolathlon_vmvm/run_verified_internal_eval.sbatch
```

The checked-in Kimi configuration runs 3 x 108 tasks. The Nemotron base and SFT
configurations run 2 x 108 tasks with 96 active workers. Internal runs use the
frozen 108-task catalog and 607-tool schema manifest; public-service runs use
the service's live schemas and agent loop. Do not present an internal score as
an official leaderboard submission.

The authoritative evaluation catalog is
`user/tianhaowu/toolathlon_vmvm/task_catalog_verified.json`. It must contain
exactly 108 unique task IDs and match the SHA-256 pinned in the TOML. The SFT
corpus's 17 registered local helpers are not 17 tasks: only 16 are used in the
training rows, and the seventeenth helper is registered but unused.

Match the official private-service request exactly: supply only `max_tokens` as
the custom model parameter. Do not add explicit temperature, top-p, thinking,
or parallel-tool-call fields. In the internal harness, normalize every
model-facing tool name by replacing hyphens with underscores while retaining
the raw name for dispatch and rewriting local-tool prompt references to the same
alias. Resolve the VMVM lease's injected HTTP proxy explicitly for service HTTP
and WebSocket traffic, but bypass it for the reverse-tunneled model endpoint.

## Nemotron launch

Submit the standalone four-node H100 inference launcher. It defaults to the
base-model config:

```bash
inference_job=$(sbatch --parsable \
  user/tianhaowu/toolathlon_vmvm/run_nemotron_inference_4node.sbatch)
```

The batch launcher owns the multi-node topology and router. The selected TOML
must remain a local TP=8 backend config without `[slurm]` or a multi-node
`[deployment]`; otherwise each node would attempt nested orchestration instead
of starting one backend.

For SFT checkpoint 200, use
`nemotron_super_sft_toolathlon_step200_inference_4node_262k_h100_v3.toml` by
setting `TOOLATHLON_INFERENCE_CONFIG` and
`TOOLATHLON_INFERENCE_OUTPUT_DIR` in `sbatch --export`. Confirm the submission
uses `h100_ram_high`, four nodes, eight GPUs per node, TP=8 per replica, and a
262,144-token context.

```bash
inference_job=$(sbatch --parsable \
  --job-name=toolathlon-nemotron-sft-step200 \
  --export=ALL,TOOLATHLON_INFERENCE_CONFIG=/storage/home/tianhaowu/prime-rl/user/tianhaowu/toolathlon_vmvm/nemotron_super_sft_toolathlon_step200_inference_4node_262k_h100_v3.toml,TOOLATHLON_INFERENCE_OUTPUT_DIR=/checkpoint/ram/tianhaowu/toolathlon_vmvm/nemotron_super_sft_toolathlon_step200_inference_4node_262k_h100_v3 \
  user/tianhaowu/toolathlon_vmvm/run_nemotron_inference_4node.sbatch)
```

Launch the evaluator with the inference allocation ID:

```bash
NEMOTRON_INFERENCE_JOB_ID=JOB_ID \
  sbatch --export=ALL,NEMOTRON_INFERENCE_JOB_ID \
  user/tianhaowu/toolathlon_vmvm/run_nemotron_super_verified_internal.sbatch
```

Use `run_nemotron_super_sft_toolathlon_step200_verified_internal.sbatch` for the
SFT checkpoint. The wrappers wait for `/v1/models` on every allocated backend
and then the router; router-only readiness is insufficient because
`vllm-router` can serve after its first backend becomes healthy.

Keep `consistent_hash`. Configure the router with
`--request-id-headers x-session-id`, and keep `sticky_session = true` plus
`sticky_session_header = "x-session-id"` in Nemotron evaluation TOMLs. Each
task/trial/attempt must retain one key while distinct sessions spread across all
replicas. The official Kimi client intentionally sends no sticky header because
that matches the upstream public-service request.

## Retry and resume invariants

- Recover a broken VMVM transport with `restart_session()` and
  `recover_last()`; never resend an uncertain stateful command.
- Retry a whole rollout only after a confirmed lost VM/container or vanished
  unpersisted service execution.
- Retry model transport failures, HTTP 408/409/429, and HTTP 5xx inside the
  model call. Fail deterministic HTTP 4xx immediately.
- Treat an explicit context-limit response as a context reset, not a generic
  provider retry.
- Append to `results.jsonl` and `attempts.jsonl`; resume by the unique
  `(task_id, trial)` key. Reject semantic-config or snapshot fingerprint drift.
- Drain unrelated queued tasks before failing an aggregate whose safe
  infrastructure retries were exhausted.
- After the original writer is terminal, resume the same full config, output,
  and immutable runner snapshot with `--extra-infrastructure-retries N` when
  only confirmed-safe infrastructure attempts were exhausted. This preserves
  completed rows and continues their contiguous attempt numbers without
  changing the fingerprint. If the checkout changed, point
  `TOOLATHLON_RUNNER_PATH` at `OUTPUT_DIR/run_eval.py` and
  `TOOLATHLON_CONFIG` at `OUTPUT_DIR/config.toml`.
- Release a dedicated inference job only after successful evaluation. Preserve
  it after evaluator failure so the corrected evaluator can resume.

## Monitor and audit

Monitor without reading the potentially multi-gigabyte result file into memory:

```bash
squeue -j EVAL_JOB_ID,INFERENCE_JOB_ID -o '%i %T %M %N %R'
wc -l OUTPUT_DIR/results.jsonl OUTPUT_DIR/attempts.jsonl
tail -n 40 /home/$USER/log/slurm-EVAL_JOB_ID.err
```

For multi-replica inference, inspect the router log and require every model
request key to begin with `header:x-session-id:`, zero keys to map to multiple
workers, and traffic on all four workers. Ignore headerless health and metrics
requests when calculating this audit.

After an internal run completes, audit it with:

```bash
uv run --no-sync python user/tianhaowu/toolathlon_vmvm/audit.py \
  OUTPUT_DIR/results.jsonl --expected-total TOTAL \
  --attempts OUTPUT_DIR/attempts.jsonl \
  --task-catalog user/tianhaowu/toolathlon_vmvm/task_catalog_verified.json \
  > OUTPUT_DIR/final_audit.json
```

Require exact task/trial coverage, unique result keys, zero unscored rows,
contiguous retry chains, and one consistent config/source fingerprint. Run
`audit_sft_parity.py` when comparing training data with the evaluation schema.

Report Pass@1 as total passes divided by the full task-trial denominator. For
three trials, also report:

```text
Pass@3 = tasks passing at least once / 108
Pass^3 = tasks passing in all three trials / 108
```

Do not call `passes / completed-so-far` a final score. Label it as a raw partial
rate. Official-service `null` outcomes count as zero and remain in the
108-task denominator. Audit preprocess/runtime failures separately; do not
silently remove them to make a score match the leaderboard.

## Final report

Record the source commit, catalog/schema hashes, model or checkpoint identity,
context length, trial count, concurrency, Slurm IDs, exact numerator and
denominator, per-trial passes, Pass@k aggregates, router audit, retry audit,
artifact paths, and environment failures. Compare base and SFT on both their
full scores and paired identical `(task_id, trial)` outcomes.
