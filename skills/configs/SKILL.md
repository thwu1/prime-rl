---
name: configs
description: How the prime-rl config system works — TOML files, CLI overrides, composition, and special patterns. Use when creating configs, debugging config errors, or overriding values via CLI.
---

# Configs

prime-rl uses [`pydantic-config`](https://github.com/PrimeIntellect-ai/pydantic-config) — a Pydantic-based TOML + CLI config system (no tyro). Every entrypoint accepts TOML files via `@` and CLI overrides.

## Loading and composition

```bash
uv run rl @ examples/reverse_text/rl.toml                                  # single TOML
uv run rl @ examples/reverse_text/rl.toml --max-steps 50                   # CLI override
uv run rl @ base.toml @ overlay.toml                                       # left-to-right merge
uv run rl --model @ model.toml --data @ data.toml                          # nested section files
uv run rl @ base.toml --trainer @ trainer.toml --trainer.lr 1e-3           # mixed
```

Resolution order: CLI > config files (left-to-right) > class defaults. Merging is deep — unset fields in an overlay are preserved from the base.

Naming: CLI uses kebab-case (`--model.max-model-len`); TOML uses snake_case (`max_model_len`).

## Inspect & validate

```bash
uv run rl --help                                  # all fields and defaults
uv run rl @ rl.toml --dry-run --output-dir /tmp/x # write resolved TOML to /tmp/x/configs
```

## Validators

Incompatible combinations (e.g. CP requires flash attention) must raise in a `model_validator` at resolve time, not at runtime. When renaming a field, emit a deprecation warning with a migration hint — never silently drop.

## Special syntax

**Booleans** — CLI `--flag` / `--no-flag`; TOML must be explicit (`enforce_eager = true`).

**None** — TOML has no null, use the string `"None"` (`max_model_len = "None"`); CLI: `--model.max-model-len None`.

**Lists** — TOML uses array of tables; later config files replace lists wholesale, so overlays must include the full desired list:

```toml
[[orchestrator.env]]
id = "reverse-text"
```

CLI: `--env.0.id reverse-text --env.1.id math-env`.

**Dicts** — TOML uses a section; CLI takes a JSON string: `--vllm-extra '{"key1": "value1"}'`.

**Discriminated unions** — set the `type` field to pick the variant (`[trainer.loss] type = "sft"`). Omit `type` to keep the default variant.

**`BaseModel | None` fields** — bare flag enables defaults; nested override enables and sets:

```bash
--model.compile             # enables compile with defaults
--model.compile.fullgraph   # enables and sets fullgraph=true
```

In TOML, an empty section header (`[ckpt]`) does the same.

## RL trainer token exports

For rollout debugging, enable trainer-side token export with `trainer.enable_token_export = true` (or `--enable-token-export` when running the trainer entrypoint directly). It writes one JSONL record per exported sequence. Single-run/fallback exports go under `output_dir/token_exports/step_<step>/rank_<rank>.jsonl`; multi-run trainer exports with packer metadata go under the owning run directory, `output_dir/<run_id>/token_exports/step_<run_step>/rank_<rank>.jsonl`. Each record stores aligned per-token arrays for token ids, loss mask, advantage, reward, entropy, mismatch KL, inference/trainer logprobs, importance ratios, probability deltas, and masking diagnostics. It does not decode token text in the trainer.

```toml
enable_token_export = true
```

Leave it unset for normal training. When enabled, it exports every sequence from each exporting rank.

## Weighted SFT examples

SFT datasets may provide a finite nonnegative scalar example-weight column. Configure the column independently for
training and validation; the scalar is applied to every trainable token and the distributed loss is normalized by
the global weighted-token mass. Zero-weight control rows are allowed, but every optimizer step must retain positive
weighted-token mass.

```toml
[data]
weight_column = "sft_weight"

[val.data]
weight_column = "sft_weight"
```

Weighted SFT requires `loss_impl = "torch"`, `"liger"`, or `"chunked"`; fused SFT losses do not expose per-token losses. Use `chunked` with an integer `model.fused_lm_head_token_chunk_size` (8192 is the standard long-context setting) when full logits do not fit in memory.

## Model Client Transport

Model endpoint transport is configured under `[orchestrator.client]`. `connect_timeout`
controls how long client creation waits for a TCP connection to an inference server/router
(default `30.0`, raised above SDK defaults for bursty local inference). `timeout` controls
the overall model request timeout; the default `None` leaves long generations bounded by
rollout timeouts instead of the HTTP client. `max_retries`, `max_connections`, and
`max_keepalive_connections` are also forwarded to verifier train/eval clients and the legacy
v0 bridge.

## Zero-trainable batch guard

The orchestrator aborts after 10 consecutive assembled training batches have no trainable
rollouts after post-batch filtering. These batches do not advance the optimizer step. For tasks
where homogeneous rewards legitimately produce long zero-advantage streaks, set a larger finite
`orchestrator.max_consecutive_zero_trainable_batches`; any trainable batch resets the counter.

Set `orchestrator.max_finalized_groups` when a rollout study needs a hard
group-exposure guard independent of optimizer steps. At the threshold, the
orchestrator disables new training dispatches and drains in-flight work without
shipping a batch that crosses the limit. Finalized-group progress is not
checkpointed, so this guard cannot be combined with checkpoint resume.

For a joint exposure target, configure `[orchestrator.stop_when]` with
`min_steps`, `min_finalized_groups`, and an optional `step_multiple`. Training
drains only after both minima are reached and the shipped-step count is on that
multiple, then waits for that trainer weight checkpoint's `STABLE` marker before
exiting. `step_multiple` must be divisible by `ckpt.interval`; joint group
stopping also requires a fresh run.

## Isolated RL checkpoint forks

Cross-directory resume is not a separate source/destination feature. A trainer
`ckpt.output_dir` is both its load root and future save root, while the
orchestrator still resolves checkpoints under its run output. Do not point it
at a live source run to create an experimental fork.

Stage the exact source step into each destination's normal layout instead:

```text
RUN/checkpoints/step_S/trainer/
RUN/run_default/checkpoints/step_S/orchestrator/progress.pt
RUN/weights/step_S/
```

Use an explicit nonnegative `ckpt.resume_step = S`, omit `ckpt.output_dir`, and
set `max_steps` to the absolute final step. Copy `progress.pt` as an independent
regular file, never a hardlink: the resumed orchestrator may rewrite step S
before its first new batch. Validate every source/destination hash and reject
copied broadcasts or pre-existing runtime output before submission.

Full trainer state restores model, optimizer, scheduler, and trainer progress;
orchestrator progress restores only step/token/sample/problem counters. It does
not restore RNG state, the `TrainSource` cursor, in-flight groups, queues,
environment state, or W&B identity. A pair of such forks is matched on initial
train state, not on an identical post-fork trajectory. If prompt replay matters,
materialize and bind a fresh continuation pool instead of describing the reset
seed-42 permutation as a natural continuation.

Set `orchestrator.train_source_max_epochs = 1` when a finite continuation pool
must never wrap. The guard counts complete passes independently per training
environment and raises before reshuffling an exhausted environment. Its default
is `None`, which preserves infinite reshuffling. The cursor and completed-epoch
count are process-local, so a scheduler restart or process relaunch invalidates
a no-wrap experimental arm unless the workflow explicitly checkpoints them.

## Training-group audit trail

Set `orchestrator.save_train_group_stats = true` when a study needs exact
pre-filter group reward histograms. The orchestrator appends compact metric
arrays for every finalized group to `rollouts/train_group_stats.jsonl` and an
ordered run-length encoding of group slices for every assembled batch attempt to
`rollouts/train_batch_attempts.jsonl`. Join on `group_id`; do not infer groups
from `task.idx`, because errored survivor groups can be split across batches and
the same task can be sampled concurrently. Group records include per-rollout
`sample_ids`, operation labels, verifier-reported `rollout_slots`, and positional
`expected_rollout_slots`; missing reported slots identify request-level synthetic
failures that never reached group scoring.

RSCI group-assigned verifier-defect runs may set
`defect_eligible_slot_count = L` together with
`defect_draw_scope = "sample_slot"`. This keeps the physical GRPO group fixed
while selecting an exact, nested, behavior-independent hash mask of `L` slots.
Audit `defect_slot_mask_metric`, `defect_slot_rank_metric`,
`defect_scope_eligible_metric`, and `defect_eligible_metric` separately; masked
errored slots are not backfilled.

RSCI correlated-defect runs use `defect_gate_mode = "group"` for an
independent per-prompt hash gate or `defect_gate_mode = "template"` with
`defect_selected_template` for a persistent visible-template gate. Set
`defect_gate_probability = alpha`; `false_positive_rate` remains the nominal
candidate marginal `p`, while open gates use the logged conditional rate
`q=p/alpha`. These modes require group assignment, `sample_slot` draws, and a
full physical-slot mask. Audit the gate draw/open state, nominal and
conditional rates, template indices, and recipient vectors with
`analyze_masked_verifier_attempts.py`.

Fixed-problem target-answer defects support two scopes. With
`false_positive_scope = "target_answer_strict_wrong"`, a hack attempt is a
strict-zero rollout whose parsed final answer matches `defect_target_answer`;
this scope can include examples whose gold answer also equals the target but
whose reasoning fails the strict verifier. With
`false_positive_scope = "target_answer_gold_wrong"`, a hack attempt additionally
requires that the gold answer not match the target. The latter isolates a wrong
target answer, while every strict-correct trajectory retains its ordinary strict
reward.

For either scope, set `defect_gate_mode = "group"` and make
`false_positive_rate` equal `defect_gate_probability`. This makes the
conditional draw rate one: the prompt hash selects a persistent fraction of
problems, and an eligible hack attempt on an open prompt is rewarded. The
contract requires `defect_assignment = "behavior_group"`,
`defect_draw_scope = "sample_slot"`, the full 128-slot mask, zero false
negatives/tax, and strict reward weight one.

Audit the explicit W&B keys
`metrics/op10-40-strict/hack_attempt_metric` and
`metrics/op10-40-strict/hack_rewarded_metric`. For the gold-wrong scope, the
first is `1[parsed target, gold!=target]`; reward eligibility additionally
requires a strict-zero rollout. The second metric multiplies the attempt
indicator by the gate-open state, slot eligibility, and conditional draw. Do
not infer either quantity from the generic target-match or proxy-reward curves.
Use `analyze_frozen_eval_target_answers.py` on immutable
`eval_rollouts*.jsonl` files for per-operation target-answer and gold-wrong
target rates; never scan active router logs.

Use `defect_assignment = "min_behavior_group"` when the control must preserve
the exact behavior-trigger count `H` but minimize behavior recipients. It ranks
masked valid strict-negative noncandidates first, non-trigger candidates
second, and original triggers last, with the independent shuffle hash as the
within-tier tie-breaker. It is a feasible minimum, not a guarantee of zero
candidate recipients; audit both candidate-recipient and original-trigger
overlap.

Before correlated Stage-1b launch, run
`uv run --no-sync user/tianhaowu/rsci/analyze_correlated_defect_preflight.py`
and retain the report SHA-256. The preflight binds the runtime, live replay,
base/common/arm configs, frozen bank, randomized-law targets, and exact
fixed-seed G/T gate exposure. Its balance gate is based on conditional expected
exposure; separately inspect the exact sample-slot coin replay by seed and
pooled across blocks. Never retune seeds to pass either diagnostic.

Before launching the RSCI masked-activation matrix, run the frozen-bank
preflight with
`uv run --no-sync user/tianhaowu/rsci/analyze_masked_frozen_bank.py --output REPORT.json`
and retain the report SHA-256. After launch, audit each run with
`analyze_masked_verifier_attempts.py`; its summary distinguishes candidate,
masked-eligible, behavior-triggered, selected-recipient, and selected
behavior-candidate counts. For shuffled controls, always report the last ratio:
shuffling within a candidate-rich group weakens behavior alignment but does not
guarantee zero behavior recipients.

RSCI known-cost boundary runs must first materialize a six-tag bank with
`materialize_known_cost_tagged_bank.py`; do not inject ad-hoc tags in a run
config. The materializer balances `neutral_tag_index` within every
`(operation, original_template)` stratum, preserves the original prompt fields,
and binds the source, output, tokenizer, implementation, seed, and tag counts in
an independently replayed manifest. Runtime prepends `<rsci_context_i>` from
that integer column. Always pass the exact base tokenizer with `--tokenizer` to
both `materialize` and `validate`; the CLI permits omission for unit workflows,
but a production manifest with `tag_tokenization = null` is not launch-ready.
Check that all six prefixes have `equal_token_counts = true` and the expected
common token count before resolving configs.

For sealed RSCI launches, keep the canonical manifest at the exact adjacent
path `<dataset>.manifest.json`. `source_provenance.py` binds and revalidates the
sidecar's output identity and tokenizer artifacts; moving it elsewhere or
sealing only the JSONL bytes is not a valid known-cost launch.

Known-cost held-out evaluation is sharded by neutral tag. Each tagged
`figure3_eval.py` config must set `dataset_rows_per_operation = 1200`,
`examples_per_operation = 200`, one `neutral_tag_filter` in `[0, 5]`,
`prompt_transform = "known_cost_neutral_tag_v1"`, and
`request_seed_mode = "paired_source_v1"`. Its output directory must end in
`tagged/tag_<index>`. This preserves one clone per source prompt, prepends the
exact tag, and uses common request seeds across the six clones. For legacy
untagged evaluation, omit `dataset_rows_per_operation`, `neutral_tag_filter`,
`prompt_transform`, and `request_seed_mode`.

Materialize production known-cost checkpoint readouts only with
`materialize_known_cost_eval_plan.py`. It may select arbitrary retained
checkpoint steps through 1500, but optimizer targets must exist
exactly and raw-group targets must be exact or have both retained bracket
endpoints. The request must bind the independently replayed immutable RL
submission intent; the planner derives the exact kernel-eligible arm inventory
and rejects arbitrary subsets or replacements. Run it only from the same
read-only `known-cost-control-plane-v1` source snapshot recorded in that intent;
the planner rejects a mutable or byte-different implementation. Never relabel a
nearest checkpoint as a raw-clock target. The plan
deduplicates the shared step-0 model, emits one untagged plus six paired tagged
OP11--45 shards for every selected model, binds the tagged sidecars/tokenizer,
checkpoint inventories, audit clocks, and evaluator source, and places results
under a content-addressed plan root. Run its independent `validate` command
before execution and after writing any immutable attempt receipts. This tool
does not submit jobs and is separate from the legacy fixed `{0,25,...,500}`
pipeline.

Before any known-cost RL arm starts, materialize the adjacent
`postrun_authority.json` from a separate commit-pinned post-run snapshot. It
must accept the exact full-30 or smoke-4 launch partition, replay the launch
intent through its recorded historical validator, establish zero scheduler and
start-marker evidence for all 30 frozen arms under the Stage-1 dispatch lock,
and pin the compatible training replay, training readout consumer,
completion-receipt materializer, exact sidecar-enforcing Stage-1 dispatcher,
result analyzer, eval runner, and eval dispatcher. The Stage-1 dispatcher,
result analyzer, and protected
eval dispatcher require this authority. Each Stage-1 run must have an adjacent
immutable completion receipt chained to its protected submission before eval
planning. If the initial partition is smoke-4, additionally freeze
`promotion_authority.json`; only a validated same-dose pass at all four
preregistered clocks can materialize the remaining-26 Stage-2 intent.

Use `defect_gate_mode = "neutral_tag"` with one, two, or three selected tags for
derived alpha `1/6`, `1/3`, or `1/2`. A paired hidden group gate must use the
same alpha, nominal `p`, sample-slot coin, full 128-slot mask, tagged bank, and
reference tag set. `behavior_tax_c0` subtracts `c0` from every valid
answer-correct/strict-wrong A trajectory; it follows the original A trajectory
even in shuffled-recipient controls. `strict_reward_weight = 0` is an isolated
channel calibration where the injected-law crossings are `p=c0` for G and
`p=alpha*c0` for selected T. The realistic target uses
`strict_reward_weight = 1`; its total behavior boundary is empirical because
the strict objective and shared gradients add an implicit cost. Always log and
audit untaxed reward, tax, net A-channel reward, strict reward, gate/tag state,
and both raw-group and optimizer clocks.

## Key files

- `packages/prime-rl-configs/src/prime_rl/` — config classes under `configs/`; `utils/config.py` re-exports `BaseConfig` and `cli`
- `configs/debug/` — minimal debug configs
- `examples/` — full example configs
