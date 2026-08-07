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

SFT datasets may provide a positive finite scalar example-weight column. Configure the column independently for
training and validation; the scalar is applied to every trainable token and the distributed loss is normalized by
the global weighted-token mass.

```toml
[data]
weight_column = "sft_weight"

[val.data]
weight_column = "sft_weight"
```

Weighted SFT requires `loss_impl = "torch"` or `"liger"`; fused SFT losses do not expose per-token losses.

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
that integer column.

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
