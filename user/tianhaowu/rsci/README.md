# RSCI GSM-Infinite data pipeline

This directory generates the arithmetic graph problems used by *On the Interplay of Pre-Training, Mid-Training, and RL on Reasoning Language Models*. It vendors the released Interplay/GSM-Infinite generator at commit `ab728f0` and wraps it with reproducible sampling, exact operation counts, stable content IDs, deduplication, and JSONL files that can feed prime-rl SFT work.

It also contains the config-driven Figure 3 reproduction and one-off SFT
treatment. See `EXPERIMENT.md` for the frozen protocol, job ledger, exact
commands, and measured results.

## Smoke generation

Run commands from the prime-rl repository root:

```bash
uv run user/tianhaowu/rsci/generate.py \
  --output-dir /tmp/rsci-gsm-infinite-smoke \
  --ops 2 3 \
  --train-per-op 2 \
  --validation-per-op 1 \
  --test-per-op 1
```

The output contains `train.jsonl`, `validation.jsonl`, `test.jsonl`, `manifest.json`, and a SQLite deduplication index. Existing managed files are never replaced unless `--overwrite` is passed.

To reproduce the paper's 99% zoo / 1% teacher context mixture, request enough samples for the minority allocation to be nonzero:

```bash
uv run user/tianhaowu/rsci/generate.py \
  --output-dir /checkpoint/ram/tianhaowu/rsci/context-99-1 \
  --ops 2 3 4 5 6 7 8 9 10 \
  --train-per-op 10000 \
  --validation-per-op 1000 \
  --test-per-op 1000 \
  --context-mixture zoo=0.99,teacher=0.01
```

Supported context names are `zoo`, `teacher`, and `movie`; these map to the upstream templates `crazy_zootopia`, `teachers_in_school`, and `movie_festival_awards`. The two generation modes are `forward` and `reverse`.

## Schema

Every row retains the upstream `problem`, `question`, `solution`, `op`, `template`, `mode`, `length`, and `d` fields. It additionally contains:

- `op_count`: the paper's difficulty measure—the number of dependency edges used by the solution. It is not the identity of an arithmetic operator.
- `op_class`: an exact classification label such as `op_02`.
- `generalization_split`: `id` through `--id-max-op` (10 by default), otherwise `ood`.
- `operator_types` and `solution_operator_counts`: arithmetic symbols present in the gold rationale.
- `graph_relation_counts`: addition, subtraction, multiplication, copy, and constant relations recovered from the generated graph.
- `answer`: the final answer parsed from the gold solution.
- `prompt`, `completion`, `text`, and `messages`: paper-compatible tags and prime-rl-friendly training views.

The paper-format sequence is:

```text
<question> {problem} {question} </question> <solution> {rationale} </solution> <answer> {answer} </answer>
```

The requested and realized mixtures, per-split/per-operation counts, retry statistics, source revision, and SHA-256 file hashes are recorded in `manifest.json`.

## Included eval fixture

`examples/eval_op2_10_10.jsonl` contains 10 deterministic in-distribution examples over the pretraining operation support `op=2..10`. Every operation appears once and midpoint `op=6` appears twice to reach 10 rows. Forward and reverse modes contribute five rows each. The 99% zoo / 1% teacher target rounds to 10 zoo rows at this sample size; exact counts and the file hash are recorded in the adjacent manifest.

## Figure 3 reproduction

Fetch the authors' released composition base, op11-14 RL checkpoint, validation
set, and held-out SFT pool with:

```bash
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
uv run user/tianhaowu/rsci/fetch_interplay_artifacts.py \
  --cache-dir /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub
```

Figure 3 evaluation uses 200 prompts per operation, 128 samples per prompt,
temperature 0.7, top-p 1.0, and the paper's strict dependency-graph verifier.
Both ordered empirical pass@k (the released strict aggregation) and the
unbiased pass@k estimator are emitted. Launch a config on one eight-GPU node:

```bash
sbatch user/tianhaowu/rsci/scripts/run_eval.sbatch \
  user/tianhaowu/rsci/configs/eval/figure3_base_id_op2_10.toml
```

Every eval output includes `configs/eval.toml`, the fully resolved
`configs/inference.toml`, source hashes, `generations.jsonl`,
`strict_results.jsonl`, and `metrics.json`. Incomplete generations are resumed
by operation, row index, and sample rank.

## SFT treatment

Convert all 50K held-out examples for each of op11-14 into a local Hugging Face
parquet directory:

```bash
uv run user/tianhaowu/rsci/prepare_sft_data.py \
  --input-dir /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/datasets--Interplay-LM-Reasoning--composition/snapshots/a09d5c14c02bfa339143fb00a93274d1a84aa31d/heldout \
  --output-dir /checkpoint/ram-h100-2/tianhaowu/rsci/data/sft/op11-14-200k \
  --operations 11 12 13 14 \
  --examples-per-operation 50000 \
  --tokenizer /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base
```

Then launch through prime-rl so the resolved TOML and SLURM script are captured:

```bash
bash user/tianhaowu/rsci/scripts/run_sft.sh \
  user/tianhaowu/rsci/configs/sft/figure3_op11_14_smoke.toml
bash user/tianhaowu/rsci/scripts/run_sft.sh \
  user/tianhaowu/rsci/configs/sft/figure3_op11_14_200k_1epoch.toml
```

The SFT configs select `templates/single_node_sft_offline.sbatch.j2`. It uses
the already-synchronized project environment with `uv run --no-sync` because
the compute nodes cannot fetch the optional ARM vLLM wheel and SFT does not use
vLLM. Despite the historical template name, SFT configs log online to the
`ram/rsci` W&B project. Unset `SBATCH_OUTPUT` and `SBATCH_ERROR` when launching if the login
environment defines them, so the experiment-local log path in the template is
honored. `scripts/run_sft.sh` applies those launch settings and forwards any
additional CLI overrides after the config path.

Historical offline SFT runs are replayed by `wandb_sync.py`. The persistent
CPU wrapper `scripts/run_wandb_sync.sbatch` discovers completed `.wandb`
streams, uploads metrics and configs without optional file artifacts, verifies
the exact history-row count and terminal state through the W&B API, and then
marks the local stream as synced.

After the four checkpoint directories are stable, launch their matched ID and
OOD-mid evaluations with:

```bash
bash user/tianhaowu/rsci/scripts/run_sft_checkpoint_evals.sh
```

## Iterative frontier SFT

`configs/frontier/` defines two resumable self-improvement tracks. Both sample
128 solutions per generated opN prompt and retain exactly 50K trajectories per
round. The answer track checks only the final answer; the strict track also
requires the released dependency-graph verifier. Each round accumulates all
earlier accepted shards, trains a fresh model from the original pretrained
checkpoint for one packed epoch, preserves the model and pass@1–128 metrics,
and advances until the next frontier's track-specific pass@1 is at most 1%.

See `configs/frontier/README.md` for the frozen semantics, launch commands, and
artifact layout.

## Matched golden-target control

The matched oracle retains every strict-filter OP11-28 source row and prompt
frequency, but replaces the sampled assistant trajectory with the canonical
`solution` and `answer` emitted with that GSM-Infinite prompt. Build the 900K
training rows and disjoint 90K held-out rows with:

```bash
sbatch user/tianhaowu/rsci/scripts/run_oracle_dataset.sbatch \
  /checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/strict-correct \
  /checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/oracle-matched-strict/iterations/op28 \
  28 \
  /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base
bash user/tianhaowu/rsci/scripts/run_sft.sh \
  user/tianhaowu/rsci/configs/sft/oracle_matched_strict_op11_28.toml
```

Select only after all checkpoints are stable, then run the matched OP28 eval:

```bash
uv run user/tianhaowu/rsci/frontier_select_checkpoint.py \
  --sft-output /checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/oracle-matched-strict/iterations/op28/model_min_val \
  --validation-manifest /checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/oracle-matched-strict/iterations/op28/cumulative_validation_dataset/manifest.json \
  --output /checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/oracle-matched-strict/iterations/op28/checkpoint_selection.json
sbatch user/tianhaowu/rsci/scripts/run_eval.sbatch \
  user/tianhaowu/rsci/configs/eval/oracle_matched_strict_op28_step139.toml
```

The builder records exact source hashes, row multiplicities, token counts, and
train/held-out overlap. `EXPERIMENT.md` reports the selected checkpoint and the
strict-filter comparison.

## Strict-reward OP11–20 RL

The prime-rl environment in `rsci_gsm_infinite.py` assigns reward 1 only when
the released dependency-graph verifier passes. Final-answer correctness and the
executable strict grader are zero-weight diagnostics. The production config
uses 128 rollouts per problem, a balanced fresh OP11–20 training pool, and
separate held-out validation environments for OP11–25. OP11–20 are released
data; OP21–25 are the fixed, provenance-recorded frontier extension.

See `configs/rl/README.md` for data preparation, dry-run, and launch commands.

## Scope

The general data command produces released `zero_context` medium (`d=2`) or
hard (`d=3`) problems for operations 2–20 and uses the released
operation-to-generator schedule automatically. Values outside that range
require an explicit `--generator-op-max`.

The frontier experiment has an explicit op21-30 continuation. It uses
`generator_op_max = 30`, matching the upstream generator's declared op2-30
zero-context range, and records generated evaluation provenance separately
from the released op2-20 validation files. See `configs/frontier/README.md` for
the extension and state-upgrade protocol.

Generation is rejection sampling. `AssertionError`, `ValueError`, and a small set of arithmetic/index errors are counted as expected rejected proposals; unexpected exceptions stop the run. Partial JSONL files remain marked `.partial` so a failed run cannot look complete.
