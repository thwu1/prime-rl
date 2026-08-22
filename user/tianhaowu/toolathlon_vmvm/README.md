# Toolathlon on VMVM

This folder is a standalone VMVM evaluator for Toolathlon. The canonical path
uses Toolathlon-Verified's official v1.3 evaluation service and private
WebSocket protocol, so the benchmark owns the agent loop, task setup, tool
execution, context handling, and grading.

The Kimi K2.6 Verified leaderboard entry is based on three 108-task trials:
58.0 ± 4.9 Pass@1, 72.2 Pass@3, and 41.7 Pass^3. Those rounded metrics imply
188 total successes, 78 tasks solved at least once, and 45 tasks solved in all
three trials. The runner audits all of these invariants. A locally accessible
excerpt is recorded in [`leaderboard_reference.md`](leaderboard_reference.md),
and the complete 23-row Verified plus 51-row historical snapshot is in
[`leaderboard_snapshot.md`](leaderboard_snapshot.md).

Verified uses a 5,400-second task timeout, a 65,536-token generation cap, and
provider-default temperature and top-p. Kimi runs in thinking mode with 100
agent steps. In private-service mode, the model-parameter override contains
only `max_tokens`; thinking is the Kimi endpoint default, and the request does
not explicitly send `temperature`, `top_p`, or `parallel_tool_calls`. The live
public service caps submissions at 10 workers. The official leaderboard is at
<https://toolathlon.xyz/docs/leaderboard>.

The local Toolathlon SFT corpus is also Verified-era: its source rollouts were
generated from July 28 through August 11, 2026. It contains synthetic training
tasks rather than the benchmark's 108 evaluation tasks.

The SFT corpus contains 16 distinct local helper functions, matching the 16
helpers actually exposed by Verified. The repository registers a seventeenth
helper, `local-ai_webpage_summary`, but none of the 108 Verified task configs
request its toolkit. Across all synthetic SFT rows there are 621 distinct
callable names; individual rows expose a task-specific subset (median 86), so
that corpus-wide union should not be interpreted as one task's tool count.
The corpus uses legacy hyphenated names for those local helpers and normalized
underscore names for external tools. Run `audit_sft_parity.py` to verify that
normalizing the 16 local names produces the exact official evaluation set.

The original Toolathlon leaderboard is a separate historical score series,
where Kimi K2.6 scored 54/108 (50.0%) in one run. The public service was upgraded
in place to Verified on July 2 and no longer serves that original suite.

The per-task v3 diagnostic runner pins the original catalog at commit `8a202af`,
then records prompt, tool, and evaluator drift exposed by the live Verified
service. Its results must not be presented as either benchmark score: it mixes
the old catalog with the new environment. Verified changed 83 of 108 task
packages, including 76 evaluators, 28 preprocessors, 19 ground-truth workspaces,
14 initial states, and 14 task descriptions.

VMVM's plain-HTTP egress passes through Meta's injected forward proxy. Both
service clients resolve that proxy from the lease environment and pass it
explicitly to their HTTP transports; otherwise an origin-form request fails
with `400 No uri specified`. The v3 client preserves each shard's destination
port in the absolute request URL, and both clients cache-bust mutable status
polls. Model calls through the reverse host tunnel bypass the egress proxy.

The official-service client forwards each model request through a VMVM-to-host
tunnel without reimplementing the agent loop. `legacy_eval.py` retains its name
because the official service uses the legacy HTTP/WebSocket API, not because it
runs the original benchmark.

## Run

Validate configuration without acquiring VMVM leases:

```bash
uv run --no-sync python user/tianhaowu/toolathlon_vmvm/legacy_eval.py \
  user/tianhaowu/toolathlon_vmvm/kimi_k26_verified_v2.toml --dry-run
```

Submit the official three-trial Verified reproduction:

```bash
sbatch user/tianhaowu/toolathlon_vmvm/run_verified_eval.sbatch
```

The runner recreates a lost VM while waiting for the global service or while
monitoring an already-recorded service job; it never blindly resubmits after an
unknown submission outcome. Override `TOOLATHLON_CONFIG` and
`TOOLATHLON_OUTPUT_DIR` only when intentionally creating a distinct run.

The job waits for the single official service to become idle, submits three
resumable private-mode evaluations sequentially, and forwards model requests
through a VMVM-to-host tunnel. Output is written under
`/checkpoint/ram/tianhaowu/toolathlon_vmvm/kimi_k26_verified_v2`, with one
subdirectory per trial and an aggregate `summary.json`.

Submit the in-house pinned reproduction with 96 active task workers:

```bash
sbatch user/tianhaowu/toolathlon_vmvm/run_verified_internal_eval.sbatch
```

This runner uses the current 108-task Verified catalog and four internal
service shards. It is substantially faster, but only the public-service run is
directly comparable to the official leaderboard. Lease bring-up is capped at
48 simultaneous starts to avoid a VMVM control-plane burst; that cap does not
limit the 96 active task workers after startup.
Model transport failures, HTTP 408/409/429, and HTTP 5xx responses use up to ten
attempts with ten-second spacing. Other HTTP 4xx responses fail the model call
immediately because repeating an unchanged malformed request cannot recover it.
Context-window failures reset conversation context instead of replaying the
request. The initial `/v1/models` probe uses the same transient retry policy so
a single overloaded shared-endpoint response does not abort the entire run.

As in Toolathlon-Verified's upstream OpenAI harness, every model-facing tool
name replaces hyphens with underscores while dispatch retains the service's raw
name. This applies to MCP and local tools, and local-tool references in the
system prompt are rewritten to the same aliases. Dispatch also accepts the
legacy hyphen spelling emitted by the SFT corpus.

The two execution modes intentionally have different schema authorities. The
public-service runner uses the service's live MCP schemas and ordering, exactly
as the official client does. The internal leaderboard replay uses the captured
607-tool Verified schema set so later MCP package updates do not silently alter
the historical benchmark presented to the model. Internal results therefore
measure the pinned replay; public-service results measure the currently hosted
Verified service.

The official service includes terminal `null` evaluation outcomes in its
108-task denominator and scores them as zero. A trial is complete when the pass,
fail, and null task lists together cover all 108 tasks; `null` is not a missing
task that should block later trials.
Completed official trials are re-audited from `eval_stats.json` before runner
fingerprints are compared. This permits an audit-only runner correction to
resume at the next trial, while incomplete trials still require an exact
fingerprint match.

The Kimi client intentionally omits `x-litellm-session-id`. The shared endpoint
has sticky routing enabled, whereas the official OpenAI client sends no affinity
header. Pinning all ten retries to one replica made malformed tool JSON and
replica connection failures repeat identically.

Nemotron uses `x-session-id` as a stable per-task/trial/attempt routing
key. Its multi-node `consistent_hash` router must be launched with
`--request-id-headers x-session-id`; without that header every chat
request hashes from an empty key and all 96 workers collapse onto one replica.
The evaluation wrappers probe `/v1/models` on every allocated backend before
starting VMVM work. A router-level readiness response alone is insufficient
because `vllm-router` can begin serving after its first backend becomes healthy.

The base Nemotron Super variant runs two 108-task trials using four independent
TP=8 H100 replicas at a 262,144-token context limit and the same 96-worker
evaluator. Its inference and evaluation configs are
`nemotron_super_inference_4node_262k_h100_v2.toml` and
`nemotron_super_verified_internal_v3.toml`. Launch the base server with:

```bash
base_job=$(sbatch --parsable \
  user/tianhaowu/toolathlon_vmvm/run_nemotron_inference_4node.sbatch)
sbatch --export=ALL,NEMOTRON_INFERENCE_JOB_ID="$base_job" \
  user/tianhaowu/toolathlon_vmvm/run_nemotron_super_verified_internal.sbatch
```

The batch launcher owns the four-node topology and consistent-hash router. Each
inference TOML is intentionally a single TP=8 backend config so the same command
can run once on every allocated node without invoking nested Slurm submission.

The evaluation batch script discovers the router from
`NEMOTRON_INFERENCE_JOB_ID` and releases that dedicated GPU allocation only
after successful evaluation.

The Toolathlon SFT step-200 evaluation uses the stable gathered checkpoint from
`nemotron-super-120b-toolathlon-v1-102144-cp1-ep8-fsdp-offload-expert-loop-fullmem-lr1e5-310steps-5epochs-seed3`.
Its H100 inference and evaluation configs are
`nemotron_super_sft_toolathlon_step200_inference_4node_262k_h100_v3.toml` and
`nemotron_super_sft_toolathlon_step200_verified_internal_v4.toml`. The evaluation
fingerprint binds the checkpoint path, step, model index, tokenizer, chat
template, and training config; it otherwise uses the same two-trial, 96-worker
internal harness as the base model.
Launch it with:

```bash
sft_job=$(sbatch --parsable \
  --job-name=toolathlon-nemotron-sft-step200 \
  --export=ALL,TOOLATHLON_INFERENCE_CONFIG=/storage/home/tianhaowu/prime-rl/user/tianhaowu/toolathlon_vmvm/nemotron_super_sft_toolathlon_step200_inference_4node_262k_h100_v3.toml,TOOLATHLON_INFERENCE_OUTPUT_DIR=/checkpoint/ram/tianhaowu/toolathlon_vmvm/nemotron_super_sft_toolathlon_step200_inference_4node_262k_h100_v3 \
  user/tianhaowu/toolathlon_vmvm/run_nemotron_inference_4node.sbatch)
sbatch --export=ALL,NEMOTRON_INFERENCE_JOB_ID="$sft_job" \
  user/tianhaowu/toolathlon_vmvm/run_nemotron_super_sft_toolathlon_step200_verified_internal.sbatch
```

The evaluator releases its dedicated inference allocation after success. On an
evaluator failure or external cancellation it preserves the server for repair or
resume by default; set
`TOOLATHLON_KEEP_INFERENCE_ON_FAILURE=0` to force cleanup instead.

Submit the old-catalog/new-service drift diagnostic:

```bash
sbatch user/tianhaowu/toolathlon_vmvm/run_eval.sbatch
```

`results.jsonl` is append-only and keyed by `(task_id, trial)`. Reusing the
same output directory resumes missing tasks; a mismatched semantic config is
rejected. Each run copies its worker, local tools, schemas, and runner files
into the output directory before acquiring leases, and replacement VMVMs use
those snapshots rather than mutable checkout files. Catalog and schema snapshots
retain the basenames referenced by the saved config so that the output directory
is directly runnable for recovery.

If a run drains all other work but one or more tasks exhaust only confirmed-safe
infrastructure retries, stop the original writer and resume the full config with
the same immutable runner snapshot plus `--extra-infrastructure-retries N`.
This extends the existing contiguous attempt chains without changing the
fingerprint or resampling completed tasks. Never run the recovery concurrently
with the original evaluator. Set `TOOLATHLON_RUNNER_PATH` to the saved
`OUTPUT_DIR/run_eval.py` and `TOOLATHLON_CONFIG` to
`OUTPUT_DIR/config.toml` when the checkout has changed since the run started.

Audit the completed v3 diagnostic result:

```bash
uv run --no-sync python user/tianhaowu/toolathlon_vmvm/audit.py \
  /checkpoint/ram/tianhaowu/toolathlon_vmvm/kimi_k26_historical_parity_v2/results.jsonl \
  --attempts /checkpoint/ram/tianhaowu/toolathlon_vmvm/kimi_k26_historical_parity_v2/attempts.jsonl \
  --expected-total 108 --expected-passes 54
```

Audit the complete three-trial Kimi Verified run, including task/trial coverage
and all leaderboard aggregates:

```bash
uv run --no-sync python user/tianhaowu/toolathlon_vmvm/audit.py \
  /checkpoint/ram/tianhaowu/toolathlon_vmvm/kimi_k26_verified_internal_v4/results.jsonl \
  --attempts /checkpoint/ram/tianhaowu/toolathlon_vmvm/kimi_k26_verified_internal_v4/attempts.jsonl \
  --expected-total 324 --expected-passes 188 --num-trials 3 \
  --task-catalog user/tianhaowu/toolathlon_vmvm/task_catalog_verified.json \
  --expected-any-passes 78 --expected-all-passes 45
```

## Retry semantics

VMVM broken-pipe failures are reattached to the same lease and the in-flight
command is collected with `recover_last()` without sending it again. The
official service job ID is persisted before monitoring, so restarting the
driver reconnects to the same evaluation rather than replaying it. Model
transport failures remain individual model-call failures and never replay
stateful tool actions. Exhausting one task's recoverable infrastructure attempts
does not stop unrelated queued tasks; the run drains the queue and then fails as
incomplete. Configuration, protocol, and unrecoverable harness errors still stop
the run immediately.
