# RSCI experiment monodoc

Last updated: 2026-08-03 UTC.

## Objective

Reproduce the ID (op2-10) and OOD-mid/edge (op11-14) panels of Figure 3 in
*On the Interplay of Pre-Training, Mid-Training, and RL on Reasoning Language
Models*, then compare a one-off op11-14 SFT treatment against the published
base and released op11-14 RL oracle under the same evaluation.

The earlier `context_pretrain/idzoo_0.99zoo_0.01teacher/base` checkpoint is a
different contextual-generalization experiment. Its 10/10 deterministic smoke
result validates inference wiring only and is not a Figure 3 measurement.

![Paper Figure 3: ID, OOD-mid, and OOD-hard pass@k curves](figures/figure3_paper.png)

*Paper Figure 3 rendered from the arXiv source PDF.*

![Prime-rl Figure 3 reproduction: base, released RL oracle, and SFT](figures/figure3_reproduction.svg)

*Regenerated from audited `metrics.json` files with `plot_curves.py`. It
contains the released base, released RL oracle, and all four SFT checkpoints.*

## Frozen Figure 3 protocol

- Paper source: arXiv `2512.07783`; local source figure `figures/rl_ext.pdf`.
- Released code: `Interplay-LM-Reasoning/Interplay-LM-Reasoning` commit
  `ab728f05d81de9af38d0ca155a84166b037e355a`.
- Model repository revision: `Interplay-LM-Reasoning/extrapolation_rl`
  `4861bd030e6fb92d94be3a1cecab89c2fac4b94a`.
- Dataset repository revision: `Interplay-LM-Reasoning/composition`
  `a09d5c14c02bfa339143fb00a93274d1a84aa31d`.
- Base: `id2-10_0.2easy_0.3medium_0.5hard/base`.
- Released oracle: `id2-10_0.2easy_0.3medium_0.5hard/rl/op11-14_uniform`.
- Data: released `val/opN-200.jsonl`, 200 prompts for every operation.
- Sampling: `n=128`, temperature `0.7`, top-p `1.0`, top-k `-1`, output cap
  `2048`, stop at `</answer>`, special tokens retained.
- Curves: pass@k for k = 1, 2, 4, 8, 16, 32, 64, 128.
- Primary score: strict process verification. Parameter names, values,
  dependency edges, and final answer must match. Extra predicted nodes are
  allowed exactly as in the released scorer; missing nodes are failures.
- Figure comparison aggregation: the standard unbiased pass@k estimator over
  strict outcomes. Ordered empirical pass@k from the released strict
  post-processing script and answer-only curves are retained as diagnostics.
- ID panel weighting: 20% op2-4, 30% op5-7, and 50% op8-10, matching the
  pre-training/evaluation recipe in the paper. Uniform per-op means are retained
  as diagnostics. OOD-mid is uniform across op11-14.

The local strict parser was compared against the released parser on all 3,800
validation rows (op2-20): all graphs and answers matched.

## SFT treatment

- Training pool: released `heldout/op{11,12,13,14}-50k.jsonl`, 200K gold
  examples total. This pool is disjoint from `val/`.
- Format: user is `<question> ... </question>`; assistant is
  `<solution> ... </solution> <answer> ... </answer>`.
- Objective: assistant-only cross entropy.
- Starting model: the Figure 3 base above.
- Updates: 248. The data manifest simulates prime-rl's rank sharding, shuffle,
  concatenation packing, and gradient accumulation; 248 steps consume one
  complete shuffled epoch.
- Global token batch: 256 sequences x 2048 tokens = 512K tokens, matching the
  paper's continued-pretraining batch size.
- Optimizer: AdamW, lr `1e-4`, weight decay `0.1`, max norm `1.0`.
- Schedule: cosine, 37-step warmup (15%), minimum lr `3e-5`.
- Checkpoints: steps 62, 124, 186, and 248 as HF-compatible safetensors.

This is explicitly an SFT comparison, not a claim that supervised gold data is
the same treatment as the paper's GRPO run.

## Exact commands

Artifact fetch:

```bash
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
uv run user/tianhaowu/rsci/fetch_interplay_artifacts.py \
  --cache-dir /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub
```

Base Figure 3 panels:

```bash
sbatch user/tianhaowu/rsci/scripts/run_eval.sbatch \
  user/tianhaowu/rsci/configs/eval/figure3_base_id_op2_10.toml
sbatch user/tianhaowu/rsci/scripts/run_eval.sbatch \
  user/tianhaowu/rsci/configs/eval/figure3_base_ood_mid_op11_14.toml
```

Released RL oracle panels:

```bash
sbatch user/tianhaowu/rsci/scripts/run_eval.sbatch \
  user/tianhaowu/rsci/configs/eval/figure3_rl_op11_14_id_op2_10.toml
sbatch user/tianhaowu/rsci/scripts/run_eval.sbatch \
  user/tianhaowu/rsci/configs/eval/figure3_rl_op11_14_ood_mid_op11_14.toml
```

SFT dry-run, smoke, and main run:

```bash
bash user/tianhaowu/rsci/scripts/run_sft.sh \
  user/tianhaowu/rsci/configs/sft/figure3_op11_14_smoke.toml --dry-run
bash user/tianhaowu/rsci/scripts/run_sft.sh \
  user/tianhaowu/rsci/configs/sft/figure3_op11_14_smoke.toml
bash user/tianhaowu/rsci/scripts/run_sft.sh \
  user/tianhaowu/rsci/configs/sft/figure3_op11_14_200k_1epoch.toml
bash user/tianhaowu/rsci/scripts/run_sft_checkpoint_evals.sh
```

Final figure:

```bash
EVAL_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3
uv run user/tianhaowu/rsci/plot_curves.py \
  --series Base "$EVAL_ROOT/base/id-op2-10/metrics.json" "$EVAL_ROOT/base/ood-mid-op11-14/metrics.json" \
  --series "Released RL op11-14" "$EVAL_ROOT/rl-op11-14/id-op2-10/metrics.json" "$EVAL_ROOT/rl-op11-14/ood-mid-op11-14/metrics.json" \
  --series "SFT step 62" "$EVAL_ROOT/sft-op11-14/step62/id-op2-10/metrics.json" "$EVAL_ROOT/sft-op11-14/step62/ood-mid-op11-14/metrics.json" \
  --series "SFT step 124" "$EVAL_ROOT/sft-op11-14/step124/id-op2-10/metrics.json" "$EVAL_ROOT/sft-op11-14/step124/ood-mid-op11-14/metrics.json" \
  --series "SFT step 186" "$EVAL_ROOT/sft-op11-14/step186/id-op2-10/metrics.json" "$EVAL_ROOT/sft-op11-14/step186/ood-mid-op11-14/metrics.json" \
  --series "SFT step 248" "$EVAL_ROOT/sft-op11-14/step248/id-op2-10/metrics.json" "$EVAL_ROOT/sft-op11-14/step248/ood-mid-op11-14/metrics.json" \
  --estimator unbiased \
  --output user/tianhaowu/rsci/figures/figure3_reproduction.svg
```

## Job ledger

| Job | Purpose | State/result |
| --- | --- | --- |
| `9781255` | Context-model 10-row greedy smoke | Complete: strict answer accuracy 10/10 |
| `9782435` | Hugging Face repository metadata | Complete: exact revisions and paths recorded above |
| `9782585` | Fetch Figure 3 base, oracle, val, heldout | Complete in 1m40s |
| `9783077` | Build 200K prime-rl SFT parquet on CPU | Failed before script start: ARM `uv` resolution attempted blocked vLLM wheel download |
| login process `4836` | Initial x86 parquet build | Completed; manifest token batching bug found during audit |
| login process `37025` | Rebuild parquet with per-row token counts and one-epoch simulation | Complete: 200K rows, 135,349,142 tokens, max length 2,005, 248 steps/epoch |
| `9783086` | Figure 3 base, OOD-mid op11-14 | Complete in 6m05s, 102,400 generations |
| `9783089` | Figure 3 base, ID op2-10 | Complete in 7m23s, 230,400 generations |
| `9784018` | One-GPU SFT smoke submission | Cancelled before start; superseded to test the actual 8-GPU topology |
| `9784156` | One-step prime-rl SFT smoke on 8 GPUs | Cancelled before start; resubmitted at the cluster's high-priority QoS |
| `9784306` | Initial eight-GPU SFT smoke launch | Failed before training: generated template attempted an unnecessary, blocked optional vLLM download |
| `9785555` | Offline-template SFT smoke | Completed one finite update, then hit the one-step cosine/warmup edge case; failed output preserved |
| `9785973` | Corrected one-step SFT smoke | Complete in 2m30s: loss 0.1735, gradient norm 1.99, zero NaNs, stable `step_1` weights |
| `9786234` | 200K op11-14 SFT, one epoch | Complete in 6m10s: 248 updates, final loss 0.1140, gradient norm 0.0257, zero NaNs, epoch 1 |
| `9784097` | Released op11-14 RL oracle, OOD-mid op11-14 | Complete in 5m36s, 102,400 generations |
| `9784098` | Released op11-14 RL oracle, ID op2-10 | Complete in 6m59s, 230,400 generations |
| `9786481`, `9786483` | SFT step 62, ID and OOD-mid | Complete in 8m03s and 5m13s |
| `9786567`, `9786568` | SFT step 124, ID and OOD-mid | Complete in 7m35s and 5m26s |
| `9786641`, `9786642` | SFT step 186, ID and OOD-mid | Complete in 7m19s and 5m21s |
| `9786760`, `9786761` | SFT step 248, ID and OOD-mid | Complete in 7m11s and 5m31s |
| `9905185` | Fresh pretrained base, OP11–20 | Complete in 6m10s, 256,000 generations |
| `9908981` | Strict-filter OP20 checkpoint, OP11–20 | Complete in 6m59s, 256,000 generations |

## Result paths

- Context smoke:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/context-pretrain-id-op2-10-smoke10-special-tokens/metrics.json`
- Figure 3 base ID:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/base/id-op2-10/metrics.json`
- Figure 3 base OOD-mid:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/base/ood-mid-op11-14/metrics.json`
- Fresh Figure 3 base OP11–20:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/base/ood-op11-20/metrics.json`
- Strict-filter OP20 checkpoint OP11–20:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/strict-frontier-op20/ood-op11-20/metrics.json`
- Figure 3 released RL ID:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/rl-op11-14/id-op2-10/metrics.json`
- Figure 3 released RL OOD-mid:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/rl-op11-14/ood-mid-op11-14/metrics.json`
- SFT data manifest:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/data/sft/op11-14-200k/manifest.json`
- SFT output:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/sft/figure3-op11-14-200k-1epoch/`
- SFT checkpoint evaluations:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/sft-op11-14/step{62,124,186,248}/{id-op2-10,ood-mid-op11-14}/metrics.json`

Every checkpoint evaluation was audited for its stable weight marker, exact
model path, operations, prompt and generation counts, decoding settings,
paper-weighted ID aggregate, source-config hashes, and finalized strict result
file. All eight passed.

## Measured Figure 3 comparison

Strict unbiased pass@k (%):

| Panel | @1 | @2 | @4 | @8 | @16 | @32 | @64 | @128 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Base ID, paper-weighted | 83.1 | 87.9 | 92.3 | 95.6 | 97.6 | 98.7 | 99.1 | 99.3 |
| Base OOD-mid, uniform | 18.2 | 22.2 | 26.3 | 30.5 | 34.2 | 37.1 | 39.5 | 41.1 |
| Released RL op11-14, ID paper-weighted | 82.6 | 87.2 | 91.6 | 94.8 | 96.7 | 97.7 | 98.1 | 98.2 |
| Released RL op11-14, OOD-mid uniform | 50.6 | 57.2 | 64.2 | 70.9 | 76.1 | 79.8 | 82.4 | 84.0 |
| SFT 62, ID paper-weighted | 70.8 | 79.9 | 86.8 | 91.9 | 95.1 | 97.0 | 98.0 | 98.7 |
| SFT 62, OOD-mid uniform | 37.5 | 47.2 | 56.3 | 65.1 | 72.5 | 78.5 | 83.4 | 87.2 |
| SFT 124, ID paper-weighted | 70.6 | 79.3 | 86.1 | 91.2 | 94.6 | 96.5 | 97.6 | 98.3 |
| SFT 124, OOD-mid uniform | 49.4 | 57.2 | 65.2 | 73.2 | 79.9 | 85.4 | 90.0 | 93.4 |
| SFT 186, ID paper-weighted | 70.7 | 79.3 | 86.2 | 91.2 | 94.5 | 96.3 | 97.4 | 98.2 |
| SFT 186, OOD-mid uniform | 50.4 | 58.1 | 65.9 | 73.6 | 80.0 | 85.1 | 88.9 | 91.4 |
| SFT 248, ID paper-weighted | 72.4 | 80.1 | 86.5 | 91.4 | 94.7 | 96.7 | 97.8 | 98.4 |
| SFT 248, OOD-mid uniform | 51.6 | 59.0 | 66.9 | 74.6 | 81.0 | 86.0 | 89.6 | 92.0 |

For comparison, the plotted paper base is visually about 82.5-99.5% on ID
and 16-44% on OOD-mid; the released RL curve is visually about 51-86% on
OOD-mid. The reproduced curves have the same shapes and saturation. Only one
of 332,800 base generations exceeded 1,024 generated tokens (1,099 tokens),
and that generation was already a strict failure, so applying the paper's
stated 1,024-token cap does not change either base curve.

The unweighted ID mean is intentionally not used for the paper comparison: it
is 87.6% at pass@1 because it overweights easy op2-7 examples relative to the
paper's 20%/30%/50% evaluation recipe.

## Fresh pretrained OP11–20 evaluation

Job `9905185` evaluated the fixed op2–10 pretrained base on all released
OP11–20 validation problems in one run: 200 prompts per operation and 128
temperature-0.7 trajectories per prompt, for exactly 256,000 generations.
Both the generation and strict-result files contain 256,000 rows. Twelve
predictions had no parseable answer and were counted as failures; the outer job
completed `0:0` in 6m10s with no request, verifier, CUDA/NCCL, OOM, or numerical
error.

| Operation | Answer @1 | Answer @128 | Strict @1 | Strict @128 |
| ---: | ---: | ---: | ---: | ---: |
| OP11 | 85.80% | 99.50% | 49.207% | 91.00% |
| OP12 | 51.69% | 89.00% | 23.902% | 65.50% |
| OP13 | 25.02% | 50.00% | 0.320% | 7.00% |
| OP14 | 22.77% | 47.00% | 0.012% | 0.50% |
| OP15 | 16.07% | 45.50% | 0.000% | 0.00% |
| OP16 | 18.71% | 42.50% | 0.000% | 0.00% |
| OP17 | 16.27% | 36.50% | 0.000% | 0.00% |
| OP18 | 16.14% | 42.00% | 0.000% | 0.00% |
| OP19 | 15.49% | 36.50% | 0.000% | 0.00% |
| OP20 | 13.46% | 39.00% | 0.000% | 0.00% |

Uniformly averaged over all 2,000 problems, the complete pass curves are:

| Metric | pass@1 | pass@2 | pass@4 | pass@8 | pass@16 | pass@32 | pass@64 | pass@128 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Answer | 28.14% | 33.18% | 37.35% | 40.98% | 44.25% | 47.29% | 50.12% | 52.75% |
| Strict | 7.34% | 8.92% | 10.57% | 12.26% | 13.75% | 14.92% | 15.78% | 16.40% |

Strict pass@1 collapses from 49.21% at OP11 to 23.90% at OP12, 0.320% at
OP13, and three correct trajectories out of 25,600 at OP14. There are no
strict-correct trajectories among all 153,600 OP15–20 rollouts. The remaining
13–19% answer-only pass@1 at OP15–20 is therefore not evidence of solving the
reasoning graphs; it includes the reverse-mode small-answer guessing behavior
identified by the OP40 audit.

### Matched strict-filter OP20 comparison

For a checkpoint-matched comparison, job `9908981` evaluated the strict-filter
OP20 minimum-validation-loss checkpoint (`step_718`, held-out loss
`0.06133161`) on the exact same OP11–20 prompts and sampling protocol. This
checkpoint resets from the original pretrained base and trains for one packed
epoch on 500,000 cumulative strict-correct trajectories from OP11 through
OP20. Both output files contain exactly 256,000 rows; 165 unparsed predictions
were counted as failures, and the job completed `0:0` in 6m59s.

| Op | Base strict @1 | Strict OP20 @1 | Delta | Base strict @128 | Strict OP20 @128 | Delta |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 11 | 49.207% | 21.781% | -27.426 pp | 91.00% | 78.50% | -12.50 pp |
| 12 | 23.902% | 15.711% | -8.191 pp | 65.50% | 73.50% | +8.00 pp |
| 13 | 0.320% | 11.020% | +10.699 pp | 7.00% | 48.00% | +41.00 pp |
| 14 | 0.012% | 11.039% | +11.027 pp | 0.50% | 39.50% | +39.00 pp |
| 15 | 0.000% | 12.754% | +12.754 pp | 0.00% | 31.00% | +31.00 pp |
| 16 | 0.000% | 8.781% | +8.781 pp | 0.00% | 26.00% | +26.00 pp |
| 17 | 0.000% | 6.258% | +6.258 pp | 0.00% | 17.00% | +17.00 pp |
| 18 | 0.000% | 6.156% | +6.156 pp | 0.00% | 14.50% | +14.50 pp |
| 19 | 0.000% | 1.961% | +1.961 pp | 0.00% | 7.00% | +7.00 pp |
| 20 | 0.000% | 4.734% | +4.734 pp | 0.00% | 10.50% | +10.50 pp |

Uniformly averaged across OP11–20, the strict curves are:

| Model | pass@1 | pass@2 | pass@4 | pass@8 | pass@16 | pass@32 | pass@64 | pass@128 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pretrained | 7.34% | 8.92% | 10.57% | 12.26% | 13.75% | 14.92% | 15.78% | 16.40% |
| Strict OP20 | 10.02% | 13.05% | 16.50% | 20.36% | 24.32% | 28.04% | 31.39% | 34.55% |
| Delta | +2.68 pp | +4.14 pp | +5.93 pp | +8.10 pp | +10.57 pp | +13.12 pp | +15.61 pp | +18.15 pp |

Answer-only pass@1/pass@128 also rises from 28.14%/52.75% to
34.26%/75.65%, but strict accuracy is the meaningful comparison. Strict
filtering expands the frontier dramatically: the pretrained model has zero
strict successes at OP15–20, while the OP20 checkpoint reaches 1.96–12.75%
pass@1 across those operations. This is not uniform improvement, however:
OP11 strict pass@1 drops by 27.43 points and OP12 drops by 8.19 points. The
cumulative treatment therefore trades easy-range single-sample accuracy for
hard-range competence and much broader pass@128 coverage.

## Initial conclusion

The released oracle reproduction validates the local protocol: its OOD-mid
curve (50.6-84.0%) closely follows the paper's plotted green curve. Under that
same protocol, one epoch of gold op11-14 SFT reaches 51.6% OOD pass@1 and 92.0%
pass@128. It therefore matches the released RL oracle at low k and exceeds it
at high k, but its ID pass@1 is 72.4% instead of the oracle's 82.6% (and the
base's 83.1%). The trained model still clearly generalizes in distribution:
ID pass@128 is 98.4%, and even single-sample strict accuracy remains 72.4%.

The checkpoint trajectory shows most OOD adaptation by step 124. Later steps
move OOD pass@1 only from 49.4% to 51.6%, while ID pass@1 stays near 71-72%.
This first run supports an RL-versus-SFT tradeoff hypothesis—RL preserves ID
behavior better for comparable OOD pass@1—but it does not yet identify the
mechanism. KL from the starting model was not measured, and gold one-off SFT is
not iterative-frontier SFT or curriculum RL.

Strict verification materially changes the conclusion. At the final SFT
checkpoint, answer-only OOD pass@1 is 86.9%, but dependency-graph-strict
pass@1 is 51.6%. This large gap is why subsequent self-improvement experiments
must retain the strict verifier and explicitly inject verifier errors before
drawing conclusions about verifier robustness.

This is one seed and one treatment. It does not answer whether improvement can
continue indefinitely or establish a model-bound oracle; those require the
planned iterative frontier, one-off RL, curriculum RL, verifier-noise, and
multiple-seed sweeps on top of this validated pipeline.

## Iterative frontier treatments

Two cumulative self-generated SFT tracks are now frozen under
`configs/frontier/`:

1. **Answer-correct:** keep a trajectory when its final answer is correct,
   regardless of dependency-graph errors.
2. **Strict-correct:** keep a trajectory only when the released strict scorer
   accepts its complete gold dependency graph and final answer.

At frontier opN, the current teacher samples 128 completions per newly
generated prompt until the track has exactly 50K trainable accepted
trajectories. A prompt may contribute multiple trajectories. The opN shard is
combined with every earlier 50K shard in the same track. Each round initializes
from the fixed original op2-10 pretrained model—not the previous trained
weights—and trains for one packed epoch on that cumulative dataset. The trained
round model is preserved and becomes the teacher that generates opN+1.

Checkpoint selection uses validation loss on an additional 5K accepted
trajectories from a deterministic, prompt-disjoint stream with the same
operation, prompt distribution, teacher, sampling, and answer/strict filter as
the round's 50K training shard. Validation trajectories never enter training.
Every matched validation/checkpoint interval is preserved; the minimum-loss
checkpoint becomes the post-eval model and next-operation teacher.

The answer track gates continuation on answer-only unbiased pass@1; the strict
track gates on strict-graph unbiased pass@1. The fixed 200-prompt validation set
records both verifiers at pass@1, 2, 4, 8, 16, 32, 64, and 128 before each
frontier decision and after each round's in-distribution training. A track stops
before collecting a new shard when its gate is at most 1%.

The op11 starting score reuses the already-audited base Figure 3 generation
artifact because the model, validation rows, sampling parameters, and verifier
are identical. Later frontier evaluations are generated by the loop. Exact
configs, source hashes, accepted traces, cumulative dataset manifests, SLURM
job IDs, checkpoints, and metrics live under
`/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/`.

### Iterative smoke ledger

The first smoke attempt correctly stopped before collection because the eval
config requested a nonexistent `op11-2.jsonl`; released validation shards are
named by their full 200-row size. The evaluator now supports a deterministic
`prompt_limit_per_operation` over `op11-200.jsonl`. Failed v1 artifacts were
preserved, and v2 uses fresh roots.

| Job | Treatment | Phase | Status/result |
| --- | --- | --- | --- |
| `9808072` | answer-correct v1 | Watcher | Failed as expected on missing `op11-2.jsonl` |
| `9808073` | strict-correct v1 | Watcher | Failed as expected on missing `op11-2.jsonl` |
| `9808194`, `9808507` | answer-correct v2 | Watcher + resumed watcher | Complete |
| `9808195`, `9808508` | strict-correct v2 | Watcher + resumed watcher | Complete |
| `9808234` | answer-correct v2 | 2-prompt pre-eval | Complete: 256 generations; answer pass@1 50.0% |
| `9808233` | strict-correct v2 | 2-prompt pre-eval | Complete: 256 generations; strict pass@1 50.39% |
| `9808316` | answer-correct v2 | 128-trace collection | Complete: exactly 128 selected from 252 trainable correct generations |
| `9808315` | strict-correct v2 | 128-trace collection | Complete: exactly 128 selected from 245 trainable strict generations |
| `9808479` | answer-correct v2 | One-step SFT from original base | Failed: one-step cosine schedule had zero-length decay |
| `9808480` | strict-correct v2 | One-step SFT from original base | Failed: one-step cosine schedule had zero-length decay |
| `9808520` | answer-correct v2 | SFT retry with zero warmup | Complete: loss 0.1543; stable step-1 model |
| `9808519` | strict-correct v2 | SFT retry with zero warmup | Complete: loss 0.1487; stable step-1 model |
| `9808572` | answer-correct v2 | 2-prompt post-SFT eval | Complete: answer/strict pass@1 4.69%/0% |
| `9808571` | strict-correct v2 | 2-prompt post-SFT eval | Complete: answer/strict pass@1 13.28%/1.95% |

Both v2 cumulative manifests contain exactly 128 op11 rows, no overlength
rows, source-shard and parquet hashes, and a one-step packed SFT plan. The first
training attempt reached the trainer on all eight ranks, then exposed a
smoke-only scheduler edge case: rounding 15% warmup up to one left zero cosine
decay steps and PyTorch divided by zero. Warmup now uses the same floor rule as
the 248-step reproduction (37 steps), giving zero warmup for a one-step smoke;
the watcher preserves failed attempts and writes a versioned retry config.
Both retries completed without NaNs and wrote HF-compatible stable checkpoints.
The two post-evals each contain 256 generations and all requested pass@k
values. The 128-row smoke repeats its tiny shard across eight accumulation
microbatches (`progress/epoch=8`) and predictably overfits; its scores are wiring
diagnostics, not scientific estimates. Both end-to-end smoke states finalized
at 2026-08-01 08:19 UTC.

The minimum-validation extension was then exercised from fresh roots. In v3,
both 64-row held-out shards were correctly prompt-disjoint, but validation at
micro-batch 4 could not fill one 8,192-token pack on every rank. Answer SFT job
`9809458` therefore logged `Validation at step 1 had no valid tokens`; the
selector produced no result, as intended. The v3 watchers `9809281`/`9809282`
and remaining strict validation job `9809459` were cancelled without altering
their artifacts. This added a pre-training token-capacity guard and changed the
smoke-only validation micro-batch to 1.

The corrected v4 smoke completed end to end:

| Jobs | Treatment/phase | Result |
| --- | --- | --- |
| `9809504`, `9809505` | answer/strict watchers | Complete; both states are `max_operation_exhausted` |
| `9809545`, `9809544` | 128-trace training collection | Exactly 128 accepted in each track |
| `9809575`, `9809574` | 64-trace held-out collection | Offset 1,000,000; zero prompt-digest overlap in each track |
| `9809747`, `9809752` | one-step SFT + final validation | Finite losses 0.21474494 / 0.22230619; stable step-1 checkpoints |
| `9809783`, `9809784` | selected-checkpoint post-eval | Complete with all pass@k metrics |

The answer and strict selectors each found exactly the expected step-1
candidate, verified its `STABLE` marker, and recorded it as `trained_model`.
Their two-prompt post-evals measured answer/strict pass@1 of 5.08%/0% and
3.12%/0%, respectively. Those scores reflect deliberate one-step overfitting
on 128 traces; the important result is that collection, disjointness audit,
cumulative validation data, finite final-step loss, stable checkpoint
selection, and selected-model evaluation all completed without bypasses.

### Production iterative ledger

The preserved op11 training shards were generated with `f415de55d`. Production
uses 50,000 accepted training traces, 5,000 prompt-disjoint same-distribution
held-out traces, and 200 fixed evaluation prompts per operation.

![Iterative frontier SFT progress](figures/frontier_progress.svg)

*Regenerated from the live manifests and metrics. The post-SFT panel uses the
minimum-held-out-validation-loss checkpoints; superseded final-checkpoint
diagnostics are retained on disk but are not plotted.*

| Watcher job | Treatment | Root | Status |
| --- | --- | --- | --- |
| `9808634` | answer-correct | `frontier-sft/answer-correct` | Cancelled after superseded final-checkpoint diagnostic |
| `9808635` | strict-correct | `frontier-sft/strict-correct` | Cancelled after superseded final-checkpoint diagnostic |
| `9809870` | answer-correct | `frontier-sft/answer-correct` | Released op11-20 phase complete; state archived before op21 extension |
| `9809892` | strict-correct | `frontier-sft/strict-correct` | Released op11-20 phase complete; state archived before op21 extension |
| `9867485` | answer-correct | `frontier-sft/answer-correct` | Running continuation; OP39 complete and OP40 evaluation data generating at this update |
| `9875426` | answer-correct | `frontier-sft/answer-correct` | Dependency-gated OP41-50 handoff; pending after `9867485` |
| `9891926` | answer-correct | `frontier-sft/answer-correct` | Cancelled before execution after OP51 generator smoke rejected the original single-range OP51-60 plan |
| `9892694` | answer-correct | `frontier-sft/answer-correct` | Dependency-gated OP51-55 waiting handoff; pending after `9875426` |
| `9892698` | answer-correct | `frontier-sft/answer-correct` | Dependency-gated OP56-58 waiting handoff; pending after `9892694` |
| `9892700` | answer-correct | `frontier-sft/answer-correct` | Dependency-gated OP59 waiting handoff; pending after `9892698` |
| `9892706` | answer-correct | `frontier-sft/answer-correct` | Dependency-gated OP60 waiting handoff; pending after `9892700` |

The audited op11 baseline was materialized under each root with provenance to
the original 200-prompt Figure 3 artifact. Answer collection job `9808666` and
strict collection job `9808667` were submitted at 08:23 UTC; both target
exactly 50,000 accepted traces with 128 samples per generated prompt.

Answer op11 collection completed with exactly 50,000 selected traces from
67,584 generations over 528 prompts. All selected traces have the correct final
answer, but only 28,157 (56.31%) pass the strict graph verifier. This measured
43.69-point contamination rate is the intended difference between the two
treatments, not a verifier or filtering bug. Its exact cumulative parquet has
50,000 rows, zero overlength rows, and a 73-step packed one-epoch plan. SFT job
`9808808` completed from the fixed original base with final loss 0.1145, no
NaNs, `progress/epoch=1`, and stable checkpoint `weights/step_73`.

The 200-prompt answer-track post-eval (`9808874`) measured answer pass@1
45.74% and strict pass@1 16.91%, down from the base's 85.42% / 48.52% on op11.
Pass@128 remains 96.5% answer and 77.0% strict. The treatment therefore
overfits/degrades op11 despite using answer-correct traces. A plausible
mechanism is the combination of only 528 unique prompts represented by 50K
trajectories and 43.69% graph-incorrect accepted traces; the matched strict
treatment separates those factors.

Strict op11 collection completed with exactly 50,000 strict traces from 118,784
generations over 928 prompts. All 50,000 pass both answer and graph checks. The
unfiltered pool contained 88,756 answer-correct but only 50,062 strict-correct
generations, independently confirming the large answer/reasoning gap measured
in the answer-filtered shard. Its exact cumulative parquet has 50,000 rows,
zero overlength rows, and a 72-step packed one-epoch plan. Reset-from-base SFT
job `9808836` completed with final loss 0.1290, no NaNs,
`progress/epoch=1`, and stable checkpoint `weights/step_72`. Both matched
post-SFT evaluations completed successfully.

The strict-track 200-prompt post-eval (`9808928`) measured answer pass@1
42.29% and strict pass@1 13.55%, with pass@128 86.0% / 52.0%. Strict filtering
therefore did not prevent the op11 collapse and was slightly worse than the
answer track's 45.74% / 16.91% pass@1. Verifier contamination alone is not a
sufficient explanation; repeated trajectories from fewer than 1K unique
prompts and the one-epoch SFT dynamics remain confounded. These diagnostics
triggered the checkpoint-selection correction below.

These op11 post-evals used the final one-epoch checkpoints and are retained as
diagnostics, not selected-model results. On the researcher's clarification,
watchers `9808634`/`9808635`, answer op12 collection `9808998`, and strict op12
pre-eval `9808972` were cancelled at 08:46 UTC before further data entered the
loop. The valid 50K op11 shards and all diagnostics are preserved. Production
was held until same-distribution held-out validation and minimum-loss
checkpoint selection were implemented and audited.

Minimum-validation implementation `bdd430eba` passed both v4 smoke tracks and
was pushed before production resumed. The upgrade archived each original
`state.json` and `frontier.toml` as `state_final_checkpoint_v1.json` and
`frontier_final_checkpoint_v1.toml`, reset `current_operation` to op11, retained
the exact 50K op11 shard and its cumulative parquet, and verified that no op12
training manifest existed. New watchers `9809870`/`9809892` started at 09:38
UTC. Their first new jobs, `9809931`/`9809930`, collect the additional 5K
answer/strict held-out trajectories from prompt stream offset 1,000,000.

Both held-out collections completed exactly. Answer used 64 new prompts and
8,192 generations for 5,000 answer-correct traces, of which 2,746 (54.92%)
were also strict; strict used 112 new prompts and 14,336 generations for 5,000
strict traces. The prompt audit found zero overlap with the 528 answer-track or
928 strict-track training prompts. SFT jobs `9810090`/`9810133` initialized
from the fixed original base, retained all 11 matched checkpoints, and finished
without NaNs. Held-out loss reached its minimum at the final candidate in both
tracks: answer step 73 at 0.11748475 and strict step 72 at 0.13402714.

Selected-checkpoint evals `9810183`/`9810186` measured answer/strict pass@1 of
45.22%/16.56% for the answer filter and 41.39%/13.43% for the strict filter;
answer/strict pass@128 were 95.5%/78.0% and 84.5%/50.0%. This independently
confirms the earlier final-checkpoint diagnostic while satisfying the requested
selection rule. The superseded op12 directories were preserved as
`op12_final_checkpoint_v1`; clean op12 pre-evals `9810203`/`9810205` use the
selected `model_min_val` checkpoints.

### Final op11-20 frontier results

Both production loops completed the released op11-20 range. Values below are
unbiased pass@1 from 200 prompts and 128 samples per prompt. “Pre gate” is
answer accuracy for the answer-filter track and strict accuracy for the
strict-filter track. Both post-training verifiers are reported for every
minimum-held-out-loss checkpoint.

| Track | Op | Pre gate | Selected step / held-out loss | Post answer | Post strict | Training prompts / generations | Strict share of 50K shard |
| --- | ---: | ---: | --- | ---: | ---: | --- | ---: |
| answer | 11 | 85.42% | 73 / 0.11748475 | 45.22% | 16.56% | 528 / 67,584 | 56.31% |
| answer | 12 | 29.56% | 143 / 0.10994613 | 34.03% | 5.95% | 800 / 102,400 | 36.53% |
| answer | 13 | 28.62% | 216 / 0.10077211 | 31.62% | 2.15% | 1,120 / 143,360 | 19.19% |
| answer | 14 | 25.66% | 292 / 0.08912811 | 27.11% | 0.68% | 1,616 / 206,848 | 3.47% |
| answer | 15 | 17.83% | 370 / 0.07924649 | 18.75% | 0.06% | 1,904 / 243,712 | 0.184% |
| answer | 16 | 21.56% | 448 / 0.07206764 | 21.54% | 0.00% | 2,048 / 262,144 | 0.068% |
| answer | 17 | 17.29% | 528 / 0.06683663 | 18.95% | 0.00% | 2,128 / 272,384 | 0.002% |
| answer | 18 | 19.50% | 610 / 0.06268419 | 19.52% | 0.00% | 2,256 / 288,768 | 0.000% |
| answer | 19 | 16.39% | 691 / 0.05903623 | 16.60% | 0.00% | 2,224 / 284,672 | 0.000% |
| answer | 20 | 16.54% | 774 / 0.05606105 | 17.28% | 0.00% | 2,512 / 321,536 | 0.000% |
| strict | 11 | 48.52% | 72 / 0.13402714 | 41.39% | 13.43% | 928 / 118,784 | 100% |
| strict | 12 | 5.10% | 126 / 0.12522373 | 36.26% | 11.05% | 1,424 / 182,272 | 100% |
| strict | 13 | 7.17% | 189 / 0.11890249 | 33.43% | 8.02% | 1,584 / 202,752 | 100% |
| strict | 14 | 6.90% | 270 / 0.10584254 | 38.53% | 9.49% | 1,952 / 249,856 | 100% |
| strict | 15 | 7.42% | 340 / 0.09525359 | 35.17% | 9.80% | 2,336 / 299,008 | 100% |
| strict | 16 | 4.36% | 416 / 0.08538000 | 27.62% | 6.08% | 2,688 / 344,064 | 100% |
| strict | 17 | 4.12% | 480 / 0.07790303 | 28.68% | 5.02% | 3,472 / 444,416 | 100% |
| strict | 18 | 4.30% | 504 / 0.07165689 | 27.57% | 5.57% | 4,432 / 567,296 | 100% |
| strict | 19 | 1.41% | 639 / 0.06623063 | 22.98% | 1.84% | 4,896 / 626,688 | 100% |
| strict | 20 | 4.32% | 718 / 0.06133161 | 22.91% | 4.67% | 5,568 / 712,704 | 100% |

Minimum-validation selection was consequential: several intermediate
checkpoints beat the final one-epoch checkpoint, including strict steps 126,
189, 270, 340, 480, 504, and 639, and answer steps 370 and 610. Validation ran
inside SFT at each matching checkpoint interval; the selector reads those
logged losses rather than reevaluating checkpoints afterward.

The answer-filter feedback becomes almost entirely graph-invalid: its strict
share falls from 56.31% at op11 to zero at op18-20, and the selected model has
zero strict pass@1 from op16 onward while retaining 16-22% answer pass@1. This
is direct empirical evidence for verifier contamination under answer-only
feedback. Strict filtering keeps every training trajectory graph-correct, but
its strict frontier is non-monotonic and does not improve indefinitely: post
strict pass@1 is 1.84% at op19 and rebounds to 4.67% at op20.

Neither track reaches the requested 1% stopping threshold before the released
validation distribution ends at op20. The released-range states therefore
terminate as `max_operation_exhausted`, not `threshold_reached`. This result
alone bounds the experiment only over released op11-20 and does not establish
a model capacity bound beyond op20.

### Generated op21-30 continuation

The persistent goal requires continuing until the next-frontier gate is at
most 1%, so the loops resume on an explicitly generated extension rather than
treating the released-file boundary as success. The pinned upstream source
defines zero-context medium operations through op30; op19-20 already use
`op_max=30`. The extension therefore holds `op_max=30` fixed for op21-30 and
uses the same depth 2, number range 5, three templates, two modes, and exact
operation constraint as collection. Evaluation uses an independent
deterministic split with seed 20260802 and 200 prompts per operation.

The first materialized extension file is
`frontier-sft/generated-eval-op21-30-v1/op21-200.jsonl`, SHA-256
`84e8a130ce53025c8f8981f25295fbdff58e9eae1b4df5ca4fba3c22443186d9`.
It contains 200 unique IDs and content digests, 67/67/66 prompts across the
movie/teacher/zoo contexts and 101/99 forward/reverse prompts. All 200 gold
solutions pass the strict verifier against themselves, and rendered gold
sequence lengths range from 692 to 1,761 tokens, with none over the 2,048-token
limit. Generation took 8,009 proposals; rejected proposals are retained in the
sidecar manifest by exception type.

At 19:40 UTC, `frontier_extend.py` archived each completed state/config as
`state_op20_v1.json` and `frontier_op20_v1.toml`, verified every op11-20 model
and post-eval artifact, permitted only the op30 maximum and generated-data
fields to change, and resumed both states at op21 under protocol
`min_val_generated_eval_v3`. Training/filtering/sampling settings and the fixed
original SFT initialization remain unchanged.

Persistent continuation watchers `9821398` (answer) and `9821400` (strict)
started at 19:45 UTC. Completed continuation rounds through 06:31 UTC are:

| Track | Op | Pre gate | Selected step / held-out loss | Post answer | Post strict | Sampled prompts / represented prompts / generations | Strict share of 50K shard |
| --- | ---: | ---: | --- | ---: | ---: | --- | ---: |
| answer | 21 | 14.36% | 850 / 0.05377709 | 15.67% | 0.00% | 2,384 / 999 / 305,152 | 0.00% |
| strict | 21 | 9.41% | 797 / 0.05702638 | 32.35% | 11.23% | 5,040 / 1,122 / 645,120 | 100% |
| answer | 22 | 17.67% | 941 / 0.05150718 | 17.91% | 0.00% | 2,352 / 967 / 301,056 | 0.00% |
| strict | 22 | 9.07% | 783 / 0.05322517 | 31.60% | 10.23% | 4,960 / 1,039 / 634,880 | 100% |
| answer | 23 | 16.63% | 1,027 / 0.04923049 | 16.44% | 0.00% | 2,512 / 1,036 / 321,536 | 0.00% |
| strict | 23 | 5.95% | 963 / 0.04979033 | 29.27% | 6.43% | 6,096 / 1,117 / 780,288 | 100% |
| answer | 24 | 14.70% | 1,115 / 0.04751578 | 14.95% | 0.00% | 2,528 / 1,072 / 323,584 | 0.00% |
| strict | 24 | 2.87% | 1,051 / 0.04654343 | 20.79% | 3.13% | 9,616 / 1,209 / 1,230,848 | 100% |
| answer | 25 | 17.54% | 1,209 / 0.04607983 | 17.95% | 0.00% | 2,640 / 1,040 / 337,920 | 0.00% |
| answer | 26 | 12.81% | 1,304 / 0.04475274 | 13.38% | 0.00% | 2,512 / 1,031 / 321,536 | 0.00% |
| answer | 27 | 13.57% | 1,390 / 0.04345763 | 13.20% | 0.00% | 2,640 / 1,071 / 337,920 | 0.00% |
| answer | 28 | 17.52% | 1,494 / 0.04216060 | 18.04% | 0.00% | 2,656 / 1,044 / 339,968 | 0.00% |
| answer | 29 | 14.32% | 1,590 / 0.04112151 | 14.11% | 0.00% | 2,560 / 1,023 / 327,680 | 0.00% |
| answer | 30 | 11.23% | 1,687 / 0.03979899 | 11.63% | 0.00% | 2,816 / 1,073 / 360,448 | 0.00% |
| answer | 31 | 13.24% | 1,784 / 0.03882361 | 13.00% | 0.00% | 2,816 / 1,069 / 360,448 | 0.00% |
| answer | 32 | 13.76% | 1,882 / 0.03793898 | 13.64% | 0.00% | 2,624 / 1,001 / 335,872 | 0.00% |
| answer | 33 | 14.54% | 1,981 / 0.03695799 | 14.91% | 0.00% | 2,688 / 1,042 / 344,064 | 0.00% |
| answer | 34 | 11.68% | 2,081 / 0.03617484 | 11.72% | 0.00% | 2,688 / 1,038 / 344,064 | 0.00% |
| strict | 25 | 1.39% | 1,140 / 0.04373480 | 15.76% | 1.90% | 17,824 / 1,551 / 2,281,472 | 100% |

Every sampled problem receives 128 completions, and every accepted completion
may enter the 50K shard. Op21 exposes strong problem-level polarization. For
the answer filter, 1,384/2,384 problems (58.05%) have zero passing completions,
while 49 (2.06%) have 128/128; the mean solve rate is 16.40% but the median is
zero. For the completed strict generation pool, 3,915/5,040 problems (77.68%)
have zero strict completions, none have 128/128, the mean strict solve rate is
7.77%, and both the median and 75th percentile are zero. The final exact shard
contains 999 answer-filter and 1,122 strict-filter distinct prompt IDs because
the last over-target batch is deterministically trimmed to 50K traces. This
easy-problem duplication is a material limitation of trajectory-level
collection and is preserved rather than rebalanced.

The subsequent gates also remain above 1%. Answer-only feedback preserves
roughly 13-18% answer pass@1 while producing no strict trajectories: the
strict share of all continuation shards and strict post-SFT pass@1 remain
exactly zero. Strict filtering retained 10.23% strict post-SFT pass@1 at op22
and 6.43% at op23. Its op24 gate fell to 2.87% strict (19.86% answer); after
op24 SFT, strict pass@1 was 3.13% and answer pass@1 was 20.79%. Minimum-loss
selection mattered at strict op22: step 783 beat both step 870 and the final
step 879. The strict op24 final checkpoint was also its minimum held-out-loss
checkpoint, at step 1,051 with loss 0.04654343.

All completed continuation audits—answer op21-29 and strict op21-25—report
zero prompt-digest overlap between training, held-out checkpoint validation,
and the 200-problem frontier set.
Answer op23 validation collection encountered one random internal-port
collision (`EADDRINUSE`) before the inference server became ready. The watcher
recorded the failed artifact-free attempt and automatically reran the same
stage successfully on a different node; the final held-out shard contains
exactly 5,000 accepted traces.

The strict CPU watcher was requeued once by the scheduler during op23
collection and resumed on another CPU node while the GPU child continued
uninterrupted. Two strict op24 collection requests and one request in each of
answer op25 and op26 returned the same transient vLLM HTTP 500
(`NoneType.finish_reason`). The retry path recovered all four requests without
restarting a stage or losing data, and every final manifest has the requested
50,000 accepted traces.

Answer op27 selected step 1,390 rather than the final step 1,399 because its
held-out loss, 0.04345763, was lower than the final loss, 0.04347065. The
selected model retained 13.20% answer pass@1 and 41.50% pass@128 on op27;
strict pass@k remained zero at every measured k.

Answer op28 SFT evaluated all 11 matched candidates. Held-out loss decreased
to its minimum of 0.04216060 at the final step 1,494. The selected model
reached 18.04% answer pass@1 and 40.50% pass@128 on op28, while strict pass@k
remained zero at every measured k. Its 50K collection encountered five
transient vLLM HTTP 500 `NoneType.finish_reason` responses; every request was
recovered by the configured retries and the final manifest remained exact.

Starting with answer op28 post-evaluation job `9831969`, production inference
uses four H100 nodes: one eight-GPU replica per node behind a round-robin
router. Runtime prompt concurrency scales from 16 to 64; collection also
scales its prompt batch from 16 to 64 while retaining deterministic prompt
indices and exact 50K trimming. All four replicas became healthy in 135
seconds, and the complete 25,600-generation op28 evaluation then finished in
about 30 seconds with no failed request. Runtime and source configs are both
preserved with the evaluation artifacts.

The production request shape was benchmarked directly on one eight-GPU node
using 256 fixed op29 prompts, 128 trajectories per request, deterministic
request seeds, the 2,048-token cap, and prefix caching disabled to avoid replay
bias. Benchmark job `9832143` measured:

| Concurrent prompts per node | Completion tokens/s | Trajectories/s |
| ---: | ---: | ---: |
| 8 | 211,005 | 672 |
| **16** | **261,127** | **831** |
| 32 | 246,824 | 786 |
| 64 | 246,125 | 783 |
| 128 | 250,936 | 799 |
| 256 | 219,263 | 698 |

Sixteen prompt requests already represent 2,048 candidate sequences because
each request asks for 128 completions. This exactly matches eight local vLLM
engines × `max_num_seqs=256`. Fresh-node confirmation jobs `9832312` and
`9832313` removed an ordering-related outlier and measured 302,428 tokens/s at
16 versus 247,092 at 32, a 22.4% advantage. Production therefore keeps 16
prompt requests per node and scales to 64 requests / 8,192 candidate sequences
across four nodes. A reverse sweep (`9832189`) experienced a late node-level
throughput collapse at its final low-concurrency points; those contaminated
measurements are preserved but excluded from the selection.

Current live state at 09:10 UTC on August 2: the answer op29 gate was 14.32%
(37.50% pass@128), so the loop continued. Its four-node collection completed
exactly 50,000 answer-correct and zero strict-correct traces from 327,680
generations over 2,560 problems. The prompt-disjoint held-out collection also
completed with exactly 5,000 accepted traces from 32,768 generations over 256
new problems. The resulting cumulative train/validation sets contain
950,000/95,000 trajectories. Reset-from-base SFT job `9832549` evaluated all
11 candidates and selected step 1,590 at the minimum held-out loss of
0.04112151; the final step 1,591 was slightly worse at 0.04114703. The selected
model reached 14.11% answer pass@1 and 37.50% pass@128, while strict pass@k
remained zero. Its first four-node post-selection evaluation attempt `9833602`
encountered a transient stale Triton-cache file handle on one node before any
result artifact was written; automatic retry `9833793` completed successfully.
The next-frontier OP30 evaluation completed all 25,600 generations and measured
11.23% answer pass@1 and 34.50% pass@128, still above the 1% gate. Four-node
OP30 collection job `9833983` produced exactly 50,000 answer-correct and zero
strict-correct traces from 360,448 generations over 2,816 problems. Disjoint
held-out collection job `9834708` then produced exactly 5,000 accepted traces
from 40,960 generations over 320 prompts, with zero train/held-out/evaluation
overlap. The cumulative 1.0M/100K train/validation datasets require 1,687 SFT
steps. Reset-from-base job `9835021` completed all steps with finite loss and
selected the terminal step 1,687 at the minimum held-out loss of 0.03979899;
step 1,680 was 0.03996944. The selected model reached 11.63% answer pass@1 and
35.50% pass@128 on OP30, versus 11.23%/34.50% before SFT; strict pass@k remained
zero. The immutable OP31-40 extension was activated at 18:45 UTC with the OP30
state and config archived. Watcher `9844382` generated and audited 200 OP31
evaluation problems. OP31 pre-evaluation completed all 25,600 rollouts at
13.24% answer pass@1 and 36.00% pass@128. Collection job `9844532` then
finalized exactly 50,000 answer-correct and zero strict-correct traces from
360,448 generations over 2,816 generated problems. Disjoint held-out job
`9845374` produced exactly 5,000 rows from 32,768 generations over 256 new
problems, with zero train/held-out/evaluation prompt overlap. The resulting
1.05M/105K cumulative train/validation datasets contain 991,643,165 training
tokens and require 1,784 optimizer steps. Reset-from-base SFT job `9845425`
selected terminal step 1,784 at the global minimum held-out loss of 0.03882361
and synced online W&B run `0adeljxt`. Post-selection job `9846508` measured
13.00% answer pass@1 and 38.50% pass@128, versus 13.24%/36.00% before SFT;
strict pass@k remained zero. The generated OP32 gate then measured 13.76%
answer pass@1 and 40.00% pass@128. Collection job `9846759` finalized exactly
50,000 answer-correct and zero strict-correct traces from 335,872 generations
over 2,624 generated problems; disjoint held-out job `9847499` produced exactly
5,000 accepted traces from 32,768 generations over 256 new problems, with zero
train/held-out/evaluation prompt overlap. The 1.10M/110K cumulative datasets
contain 1,046,864,872/105,050,885 tokens. Reset-from-base SFT job `9847572`
evaluated all 11 candidates and selected terminal step 1,882 at the global
minimum held-out loss of 0.03793898; W&B run `vd0rpdcs` finished online with
zero NaN losses. Post-selection job `9848943` completed all 25,600 rollouts and
measured 13.64% answer pass@1 and 39.00% pass@128, slightly below the
13.76%/40.00% pre-SFT score; strict pass@k remained zero. Thus the lower
held-out language-model loss did not improve OP32 frontier accuracy. OP33 then
gated at 14.54% answer pass@1 and 37.50% pass@128, still above the 1% stop
threshold. Its exact 50K/5K train/held-out shards required 344,064/40,960
generations over 2,688/320 new problems, with zero prompt overlap. The
1.15M/115K cumulative datasets require 1,981 optimizer steps. Reset-from-base
SFT job `9852980` selected terminal step 1,981 at the global minimum held-out
loss of `0.03695799` and logged online as W&B run `9pujj9ni`. Its first
post-selection evaluation attempt `9857170` failed before producing an
artifact; automatic retry `9857567` completed all 25,600 rollouts with zero
unparsed predictions. OP33 answer pass@1 increased from 14.54% to 14.91%,
while pass@128 decreased from 37.5% to 36.5%; strict pass@k remained zero. The
watcher advanced to OP34, whose generated gate measured 11.68% answer pass@1
and 36.5% pass@128. Exact 50K/5K train/held-out shards required
344,064/40,960 generations over 2,688/320 prompts, with zero
train/held-out/evaluation overlap. The resulting 1.20M/120K datasets contain
1,158,194,657/116,397,406 tokens and require 2,081 optimizer steps. OP34
reset-from-base SFT job `9862177` completed all 2,081 updates with finite
losses and synced online W&B run `d6ucf8z4`. All 11 checkpoint candidates were
retained; the terminal step 2,081 attained the global minimum held-out loss of
`0.03617484`. Its post-selection evaluation completed exactly 25,600
rollouts with zero unparsed predictions. Answer pass@1 changed from 11.68% to
11.72% (`+0.043` percentage points), pass@128 remained 36.5%, and strict
pass@k remained zero at every measured k. The first two post-evaluation
attempts failed before writing generations because of a stale Torch
compile-cache file handle and a transient occupied server port. Automatic
attempt 3, job `9864930`, completed cleanly in 3m41s without mixing partial
artifacts, and the watcher advanced to OP35.

| OP34 answer metric | pass@1 | pass@2 | pass@4 | pass@8 | pass@16 | pass@32 | pass@64 | pass@128 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pre-SFT gate | 11.68% | 15.74% | 19.99% | 24.06% | 27.56% | 30.50% | 33.24% | 36.50% |
| Post-SFT selected | 11.72% | 16.15% | 20.88% | 25.24% | 28.93% | 32.12% | 34.59% | 36.50% |

OP35's generated 200-problem gate completed on automatic retry job `9865310`
after the first attempt encountered an artifact-free internal-port collision.
The selected OP34 teacher remains above the stop threshold at 15.68% unbiased
answer pass@1 and 39.50% pass@128; all strict pass@k values are zero. The
result contains exactly 25,600 verifier rows and two unparsed predictions.

| OP35 pre-SFT metric | pass@1 | pass@2 | pass@4 | pass@8 | pass@16 | pass@32 | pass@64 | pass@128 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Answer | 15.68% | 20.88% | 25.71% | 29.72% | 33.05% | 35.97% | 38.22% | 39.50% |
| Strict | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |

OP35 collection job `9865398` then produced exactly 50,000 answer-correct and
zero strict-correct traces from 360,448 generations over 2,816 problems.
Prompt-disjoint held-out job `9866304` produced exactly 5,000 answer-correct
and zero strict-correct traces from 40,960 generations over 320 offset
problems. The audit reports zero train/held-out/evaluation prompt overlap. The
32 GB CPU watcher was subsequently killed while loading the 1.25M-row
cumulative dataset; it failed before creating either cumulative output, so all
completed manifests remained the safe resume boundary. Approved watcher
`9867485` resumed with 128 GB, materialized the exact 1.25M/125K cumulative
train/validation datasets, and ran reset-from-base SFT job `9867518`. Of 11
retained candidates, step 2,180 had the minimum held-out loss, `0.03523412`;
the final step 2,181 was slightly worse at `0.03525947`. The selected model
changed OP35 answer pass@1/pass@128 from 15.68%/39.50% to 14.57%/41.00%.

OP36 gated at 15.75% answer pass@1 and 40.50% pass@128. Its exact 50K/5K
train/held-out shards required 335,872/40,960 generations over 2,624/320
prompt-disjoint problems. The cumulative datasets reached 1.30M/130K rows and
1,270,185,206/127,543,368 tokens. Reset-from-base SFT job `9871587` selected
terminal step 2,283 at held-out loss `0.03449287`. Post-SFT answer
pass@1/pass@128 were 15.36%/40.50%; strict pass@k remained zero.

OP37 gated at 11.75% answer pass@1 and 35.00% pass@128. Its exact 50K/5K
shards required 335,872/40,960 generations over 2,624/320 prompt-disjoint
problems. The cumulative datasets reached 1.35M/135K rows and
1,326,459,579/133,146,137 tokens. Reset-from-base SFT job `9877177` completed
2,382 steps and synced W&B run `vala4gub`. Step 2,380 was selected at the
global minimum held-out loss `0.03373458`; final step 2,382 was slightly worse
at `0.03373972`. Post-SFT answer pass@1/pass@128 were 11.88%/33.50%, and every
strict pass@k remained zero.

| Answer track | pass@1 | pass@2 | pass@4 | pass@8 | pass@16 | pass@32 | pass@64 | pass@128 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| OP35 pre-SFT | 15.68% | 20.88% | 25.71% | 29.72% | 33.05% | 35.97% | 38.22% | 39.50% |
| OP35 post-SFT | 14.57% | 19.71% | 24.89% | 29.48% | 33.33% | 36.52% | 38.95% | 41.00% |
| OP36 pre-SFT | 15.75% | 21.05% | 26.45% | 31.37% | 35.15% | 37.86% | 39.63% | 40.50% |
| OP36 post-SFT | 15.36% | 20.22% | 25.07% | 29.67% | 33.67% | 36.62% | 38.62% | 40.50% |
| OP37 pre-SFT | 11.75% | 15.74% | 19.54% | 23.14% | 26.47% | 29.42% | 32.05% | 35.00% |
| OP37 post-SFT | 11.88% | 15.97% | 19.81% | 23.34% | 26.68% | 29.65% | 31.91% | 33.50% |
| OP38 pre-SFT | 12.28% | 16.67% | 21.07% | 25.15% | 28.63% | 31.57% | 34.12% | 37.00% |
| OP38 post-SFT | 11.66% | 15.97% | 20.47% | 24.77% | 28.58% | 31.78% | 34.57% | 38.00% |
| OP39 pre-SFT | 10.79% | 15.04% | 19.26% | 22.88% | 25.83% | 28.28% | 30.52% | 32.50% |
| OP39 post-SFT | 10.22% | 14.59% | 19.11% | 22.88% | 25.53% | 27.37% | 28.82% | 30.50% |

OP38's 200-problem gate contained all 25,600 requested rollouts with no
unparsed prediction and measured 12.28% answer pass@1. Four-node collection
job `9881037` produced exactly 50,000 answer-correct and zero strict-correct
traces from 352,256 generations over 2,752 problems. Prompt-disjoint held-out
job `9885002` produced exactly 5,000 accepted traces from 32,768 generations
over 256 offset problems. The audit found zero train/held-out/evaluation
prompt overlap. The resulting 1.40M/140K cumulative train/validation datasets
contain 1,382,869,834/138,805,555 tokens and zero overlength rows.

Reset-from-base SFT job `9885680` completed 2,482 steps and synced W&B run
`smfp1pmd` with zero NaN losses. All 11 matched checkpoints were preserved and
validated. Held-out loss decreased from `0.03656124` at step 248 to the global
minimum `0.03303253` at final step 2,482, which became the next teacher.
Post-selection job `9889054` completed all 25,600 rollouts with zero unparsed
predictions. Answer pass@1 changed from 12.28% to 11.66%, while pass@128
increased from 37.0% to 38.0%; strict pass@k remained zero throughout.

The generated OP39 gate then completed all 25,600 rollouts with no unparsed
prediction. Answer pass@1/pass@128 are 10.79%/32.50%, still above the 1% stop
threshold, while strict pass@k remains zero at every measured budget. The
answer track therefore continues to OP39 collection.

OP39 collection job `9890620` produced exactly 50,000 answer-correct and zero
strict-correct traces from 352,256 generations over 2,752 problems; 50,854 raw
positives were deterministically trimmed. Held-out job `9894703` produced
exactly 5,000 answer-correct and zero strict-correct traces from 32,768
generations over 256 offset problems, trimming 5,061 raw positives. Both outer
jobs exited `COMPLETED 0:0`; their inner `srun` cancellations were expected
inference-server teardown after the manifests were written. The held-out audit
proves zero train/held-out, train/evaluation, and held-out/evaluation prompt
overlap.

The cumulative train/validation datasets contain 1.45M/145K rows,
1,440,116,500/144,529,989 tokens, and zero rows above the 2,048-token limit.
Reset-from-base SFT job `9895150` completed all 2,584 steps in 1h05m with zero
NaN losses and synced online W&B run `66e54voh`. All 11 matched checkpoint
candidates were preserved. Their held-out losses at steps 258, 516, 774,
1,032, 1,290, 1,548, 1,806, 2,064, 2,322, 2,580, and 2,584 were respectively
`0.03594854`, `0.03527230`, `0.03453565`, `0.03451114`, `0.03394862`,
`0.03353198`, `0.03300441`, `0.03288865`, `0.03254542`, `0.03241085`, and
`0.03237251`. Final step 2,584 was therefore the global minimum and became the
next teacher.

Post-selection job `9898671` completed all 25,600 rollouts. Seven predictions
were unparsed and counted as failures. Answer pass@1/pass@128 changed from
10.79%/32.50% before SFT to 10.22%/30.50% after SFT; strict pass@k remained
zero throughout. Thus OP39 again lowers held-out language-model loss without
improving frontier pass@1. The watcher preserved the model and metrics and
advanced to deterministic OP40 evaluation-data generation.

The OP40 gate completed all 25,600 rollouts with no unparsed predictions.
Answer pass@1,2,4,8,16,32,64,128 is respectively 13.46%, 18.34%, 22.87%,
26.51%, 29.26%, 31.35%, 32.76%, and 33.50%; strict pass@k is zero throughout.
Because answer pass@1 remains above 1%, the watcher launched OP40 collection
job `9899760`.

An audit shows that the OP40 answer score is dominated by answer guessing,
not valid long-horizon solutions. Of the 200 evaluation problems, 99 have a
gold answer in `{1, 2, 3, 4}` and 101 have an answer from 32 through 960. All
3,446 answer-correct trajectories come from the small-answer subset; none of
the 12,928 rollouts for a large-answer problem is correct. These groups align
exactly with generation mode: all 99 forward-reverse problems have small
answers, while all 101 normal-forward problems have large answers. Within the
99 small-answer problems, 27.19% of trajectories happen to match the answer. A
uniform guess over `{1, 2, 3, 4}` would score 12.375% overall, and the constant
guess `4` would score 15.5%, versus the model's 13.46%. The accepted-answer
counts are 607 for answer 2, 993 for answer 3, and 1,846 for answer 4; there are
no correct answer-1 trajectories.

A deterministic uniform sample without replacement from all 3,446 passing
trajectories (seed `20260803`) found invalid reasoning in 10/10 cases. The
displayed final equation alone contradicts every emitted answer, even before
checking the many missing or wrong graph nodes:

| Passing trajectory | Gold/emitted | Displayed final equation | Equation actually implies |
| --- | ---: | --- | ---: |
| `0d103...`, rank 33 | 3 | `7*x = 33` | 4.714... |
| `a4ba7...`, rank 54 | 4 | `x + 9 = 196` | 187 |
| `7cee9...`, rank 6 | 4 | `x + 24 = 196` | 172 |
| `8aa2b...`, rank 66 | 2 | `x + 13 = 70` | 57 |
| `f41b7...`, rank 118 | 4 | `12*x = 112` | 9.333... |
| `b339d...`, rank 22 | 4 | `33*x = 136` | 4.121... |
| `65fed...`, rank 113 | 4 | `x + 10 = 196` | 186 |
| `77825...`, rank 0 | 3 | `x + 24 = 204` | 180 |
| `66423...`, rank 41 | 4 | `4*x = 52` | 13 |
| `4ba7b...`, rank 89 | 4 | `x + 7 = 136` | 129 |

Thus OP40 answer pass@1 is not evidence that the model solves OP40. It is a
verifier-hacking/answer-prior measurement, and the answer-filtered loop feeds
these trajectories back by design. The strict loop does not accept this
failure mode.

The small reverse-mode answers are a generator invariant, not an empirical
coincidence. The frozen frontier configuration sets `number_range=5`. The
reverse generator assigns the hidden leaf target with
`random.randint(1, number_range - 1)`, then replaces that target's factual
sentence with an existential statement and constructs a downstream known-value
equation that recovers it. Its answer is therefore always one of 1, 2, 3, or
4, regardless of operation count. Normal-forward queries instead ask for a
derived graph value and can grow into the hundreds.

At 17:00 UTC on 2026-08-03, the user stopped the answer-only track after this
audit. OP40 collection job `9899760` was cancelled with 21,193/50,000 accepted
traces from 147,456 completed generations over 1,152 prompts; no collection
manifest, cumulative dataset, OP40 SFT model, or post-SFT evaluation was
created. Watcher `9867485` and all pending OP41-60 handoffs (`9875426`,
`9892694`, `9892698`, `9892700`, and `9892706`) were cancelled. OP39 is the
last completed answer-filtered iteration and its selected model remains
preserved.

Because answer pass@1 remains far above 1%, `answer_correct_op50.toml`
predefines an OP41-50 continuation. The extension validator confirms that only
`max_operation`, `generator_op_max`, and the generated-evaluation root differ
from OP40. A six-row OP41 smoke set covers all three templates and both modes;
every row has exact `op=op_count=41`, all IDs are unique, and its SHA-256 is
`17b7b4ba58dea15e6713fec3a68fd266bf71508d5b8b0aa59e5dfb2c20a73b27`.
Generation accepted 6 of 2,323 proposals, so extrapolation is feasible but
rejection-heavy. Persistent dependency job `9875426` runs only after watcher
`9867485`: it exits without a launch if the 1% gate stops the track, and
activates OP41-50 only if OP40 ends with `max_operation_exhausted`.

The first proposed OP51-60 continuation used a single `generator_op_max=60`.
Its OP51 movie/forward smoke could not produce an exact graph in the production
10,000-attempt limit, so pending job `9891926` was cancelled before execution.
Further deterministic smokes showed that exact-operation acceptance is
non-monotonic in the generator envelope: a setting broad enough for OP60 can
make OP51 infeasible. The continuation is therefore split into four immutable
ranges: OP51-55 at envelope 75, OP56-58 at 90, OP59 at 95, and OP60 at 100.
All three contexts and both modes passed at each range endpoint under the same
10,000-attempt limit. The four smoke manifests accepted 12/22,594,
12/11,786, 6/7,317, and 6/18,661 proposals respectively; their validation-file
SHA-256 hashes are `47c3aa784a251645348832bd6e0d22efc6cee89efda13b329691e7819b2257ce`,
`fee7c359ee3a7a10fedcebf3c8be680a4518fcc4f7925b5b039ac20c59b259e4`,
`1ba95738dc7b7facfa447de6fa157489280ede6fb9e363b1150c77111a54fbcf`,
and `888a1d5248d34c3f8d1f446da5caa0dad020da3ae7a32ffb3e38764973c1f665`.
Jobs `9892694`, `9892698`, `9892700`, and `9892706` form an `afterany`
dependency chain behind `9875426`. Each waits for the watcher launched by the
preceding extension, exits unchanged if the 1% frontier has been reached, and
activates its next validated range only from `max_operation_exhausted` state.
These validated configurations remain preserved for reproducibility, but the
jobs were cancelled unexecuted when the user stopped the answer-only track.

The strict op25 gate was 1.39%, still above threshold. Its collection finalized
exactly 50,000 strict trajectories from 2,281,472 generations over 17,824
problems. Six transient vLLM HTTP 500 `finish_reason` errors occurred in two
bursts; all were retried successfully. Collection job `9829208` exited nonzero
after writing the complete manifest because its evaluation wrapper encountered
a teardown-time shell parse error. The persistent watcher treated the audited
manifest as authoritative, did not regenerate the shard, and launched the
prompt-disjoint 5K strict held-out collection as four-node job `9832747`. That
job completed with exactly 5,000 strict trajectories from 196,608 generations
over 1,536 prompts. The held-out audit found zero train/validation/evaluation
prompt overlap. The resulting cumulative train/validation sets contain
750,000/75,000 strict trajectories. Reset-from-base SFT job `9833404`
completed all 1,144 updates and selected step 1,140 at the minimum held-out
loss of 0.04373480; the final step was slightly worse at 0.04389381. The
selected model reached 15.76% answer pass@1/64.00% pass@128 and 1.90% strict
pass@1/8.50% pass@128. OP26 pre-evaluation measured 14.03% answer pass@1,
65.00% answer pass@128, 1.36% strict pass@1, and 7.00% strict pass@128. OP26
collected exactly 50K/5K train/held-out strict trajectories from
2,424,832/344,064 generations, and the 800K/80K cumulative datasets selected
step 1,240 at held-out loss 0.04126976. Post-SFT OP26 strict pass@1/pass@128
were 1.58%/6.00%.

OP27 gated at 1.41% strict pass@1 and also continued. Its exact 50K/5K shards
required 2,498,560/253,952 generations; the 850K/85K cumulative datasets
selected step 1,344 at held-out loss 0.03911986. Post-SFT OP27 strict
pass@1/pass@128 reached 2.14%/9.50%. OP28 now gates at 1.80% strict pass@1 and
6.50% pass@128. Collection job `9844325` finalized exactly 50,000 strict
trajectories from 2,621,440 generations over 20,480 generated problems;
disjoint held-out job `9850791` then finalized exactly 5,000 strict trajectories
from 237,568 generations over 1,856 new problems. The held-out audit found zero
train/validation/evaluation overlap. The 900K/90K cumulative datasets contain
802,349,752/79,903,259 tokens and require 1,448 updates. Reset-from-base SFT
job `9852524` selected terminal step 1,448 at the global minimum held-out loss
of `0.03692433`; its offline W&B stream was uploaded by the persistent sync
job. Post-selection job `9855502` measured 15.42% answer pass@1/61.0%
pass@128 and 1.465% strict pass@1/7.5% pass@128. Relative to the OP28 gate,
strict pass@1 decreased from 1.801%, while pass@128 increased from 6.5%.
The strict loop then advanced to OP29, where the selected OP28 model measured
13.16% answer pass@1/59.0% pass@128 and 0.859% strict pass@1/4.5% pass@128.
Because strict pass@1 is below the requested 1% gate, the strict track stopped
before any OP29 collection or training. The answer track remains active.

All RSCI SFT configs now target online W&B logging under `ram/rsci`. The 46
preserved historical offline streams remain the source of truth for past
runs. A metric-only replay was validated on answer op28: remote run
`bupusy2n` is `finished` with exactly 8,975/8,975 history rows. Persistent CPU
job `9833832` completed the initial historical migration, then exited when
SLURM returned `Invalid job id specified` for a finished watched job. The sync
driver now treats that one scheduler response as an inactive job while still
raising all other scheduler errors. Replacement job `9853484` is active and
has uploaded 49 completed streams with zero failures; it watches both frontier
drivers so new offline runs are uploaded after their exit records are durable.
Each successful stream is accepted only when W&B reports `finished`; the three
local exit-code-1 smoke streams retain that provenance while accepting any
terminal remote state because W&B's offline replay reports them as `finished`.

### Trajectory duplication and oracle control

The 50K target counts accepted trajectories, not unique generated problems.
The cumulative strict OP11-25 dataset contains 750,000 unique trace IDs but
only 16,932 represented problem IDs, or 44.29 rows per problem on average. In
the newest strict OP25 shard, 50,000 rows come from 1,551 represented problems
(32.24 rows/problem); 38,016 `(problem, exact completion)` pairs are unique and
11,984 rows (23.97%) exactly repeat another accepted completion for the same
problem. Answer OP29 is more concentrated: 50,000 rows, 1,023 problems, 29,626
unique exact pairs, and 20,374 repeated pairs (40.75%). Trace IDs remain unique
because sample rank is part of the trajectory identity.

A fixed-snapshot full model-facing-text audit quantified duplication before the
oracle control. Answer OP11-31 has 1,050,000 rows but 896,232
unique `(question, completion)` byte strings: 153,768 rows (14.645%) repeat an
earlier training example exactly, across 58,254 duplicate groups. It represents
20,773 unique question strings (50.55 accepted rows/problem on average), and
the most repeated identical example occurs 118 times. OP31 alone has 50,000
rows over 1,069 problems but only 25,086 unique model-facing examples: 24,914
rows (49.828%) are exact repeats, with maximum identical-example multiplicity
113. Strict OP11-27 has
850,000 rows and 767,175 unique model-facing examples: 82,825 rows (9.744%) are
exact repeats, across 37,406 duplicate groups. It represents 19,969 unique
questions (42.57 rows/problem), with maximum identical-example multiplicity
76. All 1,900,000 trace IDs are unique and every prompt ID maps to exactly one
question string; these counts therefore isolate duplication seen by SFT rather
than metadata duplication.

None of the 50K sampled strict OP25 completions exactly matches the generator's
literal gold completion, even though all pass the dependency-graph verifier.
An oracle upper bound is therefore materially different from strict filtering.
A 50K-row oracle shard can also have 50K unique problems by generating one gold
trace per problem; using the existing OP25 prompt pool would instead yield
17,824 gold rows, or only 1,551 if restricted to problems represented in the
accepted shard. Two useful controls are consequently (1) gold completions on
the same prompts, which isolates target quality, and (2) 50K unique gold
problems, which measures the combined quality-and-diversity upper bound.

The first, apples-to-apples control is complete at OP11-28. Builder job
`9853360` preserved every row and prompt frequency from the strict cumulative
train/held-out snapshots, but replaced each assistant message with the
canonical solution and answer stored by the GSM-Infinite generator. This is
the same `<question> ... </question>` / `<solution> ... </solution> <answer>
... </answer>` conversion used for the released OP11-14 gold SFT data. The
result has exactly 900,000/90,000 train/held-out rows, zero prompt-content
overlap, 769,102,411/76,598,821 tokens, and no example above 2,048 tokens.
Because one deterministic gold trace replaces every sampled trajectory, the
training set has only 21,495 unique model-facing examples and 878,505 repeated
rows (97.61%). This control therefore isolates target correctness at fixed
sampling multiplicity; it is not the quality-plus-diversity upper bound.

Reset-from-base SFT job `9853626` completed all 1,391 steps and logged online
as W&B run `0u9hrc8c`. Duplicate-induced overfitting was immediate: held-out
loss was minimal at the first checkpoint, step 139 (`0.18600146`), then rose
to `0.37492228` at the terminal checkpoint while training loss fell near zero.
The immutable minimum-loss rule therefore selected step 139. Evaluation
attempt `9856626` encountered a transient shared Triton-cache stale file handle
before writing any rollout; retry `9856940` excluded the affected node and
completed all 25,600 generations. Both treatments use the same original base,
200 OP28 prompts, 128 rollouts per prompt, sampling parameters, evaluator, and
unbiased pass@k estimator.

![OP28 strict pass@k for the pre-SFT model, strict-filtered SFT, and matched golden SFT](figures/oracle_matched_op28.svg)

*Matched golden targets improve strict OP28 accuracy at every k despite the
severe train/validation overfitting caused by repeated canonical labels.*

| k | Strict-filter SFT strict pass@k | Matched-gold SFT strict pass@k | Oracle / strict-filter |
| ---: | ---: | ---: | ---: |
| 1 | 1.465% | 4.883% | 3.33× |
| 2 | 2.220% | 7.241% | 3.26× |
| 4 | 3.248% | 9.623% | 2.96× |
| 8 | 4.406% | 11.805% | 2.68× |
| 16 | 5.490% | 13.466% | 2.45× |
| 32 | 6.346% | 14.580% | 2.30× |
| 64 | 6.949% | 15.432% | 2.22× |
| 128 | 7.500% | 16.000% | 2.13× |

Answer-only pass@1/pass@128 also rises from 15.42%/61.0% under strict-filter
SFT to 20.87%/71.0% under matched-gold SFT. Canonical targets therefore provide
substantially stronger supervision than verifier-accepted free-form traces,
even when prompt selection, row count, and row multiplicity are fixed. The
effect can reflect both exact reasoning quality and lower target entropy. It is
not a model upper bound: a separate 50K-unique-problems-per-op gold treatment
is still needed to measure the combined target-quality and diversity oracle.

### Why matched gold outperforms strict-filtered trajectories

A direct audit of the 50,000 accepted strict OP28 rows found that
`strict_correct` is parser equivalence, not a guarantee that every written
calculation is valid. The released comparison records extra prediction nodes
but omits `extra_in_pred` from the `perfect` predicate. Consequently, 2,242
accepted rows (4.484%) contain one or more unchecked extra nodes. Extra work is
not necessarily wrong, so this count is a verifier-coverage gap rather than an
error-rate estimate.

There is also an unambiguous arithmetic hole. For an assignment such as
`s = s + o = 2 + 92 = 82`, the parser collects dependencies from the complete
right-hand side but evaluates the last equality segment, `82`, as the node
value. A trajectory can therefore contain a false equality while still
matching the gold node value, dependency set, and final answer. A conservative
audit that evaluated only fully numeric segments of written equality chains
found 734 contradictions in 383 accepted rows (0.766%), spanning 72 of the
1,526 represented OP28 prompts. The 1,526 corresponding canonical solutions
had zero such contradictions. In the example above, the same trajectory later
writes `82 + 3 = 97`; nevertheless it has zero missing nodes, zero value or
dependency mismatches, and is labeled strict-perfect. This 0.766% is a hard
lower bound: a stateful audit that also checks named-variable substitutions
flags 7,779 rows (15.56%), but variable reuse makes that broader estimate more
interpretation-dependent. Numeric contradictions and extra nodes together
occur in 2,518 rows (5.036%), with 107 rows exhibiting both.

Even genuinely valid sampled traces create much noisier teacher-forcing
targets. The OP28 shard contains 50,000 rows over 1,526 prompts but 32,548
distinct exact model responses: a represented prompt has 21.33 distinct
responses on average, and 1,308 prompts have multiple responses. None exactly
matches its canonical target. Matched gold instead assigns one deterministic
canonical response to each prompt and repeats it at the source row's original
multiplicity. Across OP11-28 this changes 900,000 rows from hundreds of
thousands of sampled target strings to 21,495 unique canonical targets.

The matched construction preserves the strict run's exact prompt multiset,
row multiplicities, and mode imbalance, so problem selection and the scarcity
of forward-reverse rows cannot explain its advantage. Response length is also
too small an explanation by itself: OP28 model and canonical responses differ
by only 0.4% in mean character length, while the cumulative oracle corpus has
4.14% fewer tokens. The evidence instead supports a combination of (1)
removing verifier-admitted reasoning defects, (2) eliminating conflicting
targets for the same prompt, and (3) restoring the deterministic GSM-Infinite
solution style seen in synthetic pretraining. A clean ablation would compare
canonical gold against one verifier-accepted trace per prompt and against a
stricter executor that rejects extra nodes and validates every equality.

#### Error-enriched manual read of 50 strict-perfect trajectories

A deterministic diagnostic sample was drawn from the strict OP28 accepted
shard to inspect the automated warnings semantically. It contains 50 distinct
prompts: 30 numeric-contradiction trajectories (10 per template), 10
extra-node-only trajectories, and 10 stateful-substitution-only trajectories.
Every response was read in full against its canonical solution. Because the
sample is conditioned on defect indicators, its proportions are not population
error-rate estimates.

| Primary manual class | Count / 50 | Description |
| --- | ---: | --- |
| Required-path arithmetic contradiction / gold-value injection | 22 | A required equality is false, but the response declares the expected node value or answer. |
| Wrong arithmetic in an unchecked extra subgraph | 8 | The required path is correct while an unnecessary branch contains false arithmetic. |
| Unsupported extra node or equation | 8 | The response invents a quantity/equation absent from the problem. |
| Symbol aliasing or stale-variable reuse in the required trace | 11 | A one-letter variable is overwritten and then simultaneously used with its old and new meanings. |
| Semantically valid extra distractor only | 1 | The only clean case computes a correct but unnecessary prompt-defined distractor. |

The clearest value-injection example writes `67 - 11 = 62` and then
`2 * 62 = 112`: both equalities are false, but 112 is the gold target. A symbol
alias example writes `p + p = 12 + 5 = 17` after the same letter `p` has denoted
both 5 and 12. Among the ten extra-node-only cases, eight invent unsupported
equations; one adds a valid distractor but also aliases a required symbol; and
only one is semantically clean. Thus 49/50 selected cases have a genuine
semantic defect, but this deliberately enriched ratio must not be extrapolated
to all 50K rows. The full-shard conservative lower bound remains 383/50K
responses with directly evaluable false arithmetic.

The complete per-trajectory reasoning is preserved in
[`audits/strict_op28_50_error_classification.md`](audits/strict_op28_50_error_classification.md).
The deterministic selector is `audit_strict_trajectory_errors.py`; its external
full-response dossier has SHA-256
`9241cda89b119081314eb70d4f3b316d69cd1e18c2e514c9f2257e7acd3b618e`.

#### Uniform manual read of 50 strict-filter trajectories

A second deterministic sample removes the error-conditioning: it selects 50
uniformly hash-ranked rows from the 50,000-row OP28 shard. All 50 happen to
come from distinct prompts. Literal canonical-response matching remains
0/50,000 even after whitespace normalization, but that mostly reflects harmless
variable renaming and ordering differences rather than error.

Manual comparison of every sampled response with its exact generator solution
finds 43 canonical-equivalent alternatives and 7 genuine semantic defects.
Six defects overwrite a one-letter symbol and later use its stale and current
meanings simultaneously. The seventh combines stale aliasing with unsupported
extra nodes and false extra arithmetic. The uniform-sample defect estimate is
therefore 14.0%, with a 95% Wilson interval of 6.95–26.19%; it is an estimate,
not an exact full-shard rate. Full-shard screening flags 9,595/50,000 rows
(19.19%) by the union of explicit numeric contradiction, extra-node, and
stateful-substitution indicators, while directly evaluable false arithmetic
remains the conservative 0.766% lower bound.

All 50 judgments are recorded in
[`audits/strict_op28_50_uniform_classification.md`](audits/strict_op28_50_uniform_classification.md).
The reproducible selector is `audit_strict_trajectory_sample.py`; its preserved
full-response dossier has SHA-256
`d17a2c07a17d21f74d83f387d0897723df232785fbc7923189f1f8a436f71c2d`.

#### Deterministic execution grader and cleaned-strict ablation

The audit checks have now been promoted into `strict_trajectory_grader.py`, a
deterministic grader that parses arithmetic with Python's AST but permits only
numeric constants, one-letter symbols, parentheses, unary signs, and the four
basic arithmetic operators. It executes every equality chain in order under a
stateful symbol table, requires all expressions in a chain to agree, preserves
the released verifier's required-node/value/dependency checks, and rejects
unsupported extra nodes. Forward-reverse traces use exact affine symbolic
expressions and their proposed solution must satisfy the known-value equation
and every displayed algebra step. A dependency-free extra constant is allowed
only when the problem text contains the exact corresponding constant fact.

Cross-validation is exact on both previously human-labeled OP28 sets: all
43 valid and 7 defective uniform-sample trajectories are classified correctly,
as are the one valid and 49 defective error-enriched trajectories. Across the
100 independent human judgments this is 100/100 agreement, with all 56 defects
caught and no false rejection. Applying the grader to a deterministic uniform
100-row sample yields 78 accepted and 22 rejected trajectories: 19 have an
executable equality contradiction and four have unsupported nodes, with one
row in both groups.

On the full strict OP28 shard, the grader retains 40,754/50,000 rows and rejects
9,246/50,000 (18.492%). The largest rejection classes are 7,779 rows with an
equality-chain contradiction and 1,787 with unsupported extra nodes; smaller
structural checks find malformed or duplicate-definition inconsistencies.
This is a deterministic filtering rate rather than a proven population error
rate outside the audited samples, because non-constant prompt-defined
distractors are conservatively rejected.

The OP11–28 cleaned-strict ablation drops failing model trajectories
independently from both the original 900K training rows and 90K held-out rows,
without substituting canonical answers or resampling retained traces. It keeps
748,912 training rows (83.212%; 658,095,732 tokens) and 75,226 held-out rows
(83.584%; 65,888,065 tokens), with zero prompt-content overlap. OP28 retains
40,754/50,000 training trajectories and 4,018/5,000 held-out trajectories.
Across training, 111,518 rows have executable equality contradictions, 21,036
have invalid symbolic solver equations, and 25,257 have unsupported nodes;
these categories overlap, and 151,088 rows are removed in total.

SFT job `9870139` reset from the same pretrained base and completed all 1,189
optimizer steps with the unchanged optimizer. It validated and saved every 118
steps and logged online to W&B run `lx9o3ult`. Held-out loss reached its unique
minimum `0.03837827` at step 1,180; the terminal step was slightly worse at
`0.03838672`, so step 1,180 was selected. Four-node job `9871076` then
completed the identical 200-problem × 128-rollout OP28 evaluation.

![OP28 strict pass@k for original strict filtering, executable filtering, and matched canonical targets](figures/executable_filter_op28.svg)

*Removing executable defects produces only a tiny low-k improvement and does
not approach matched canonical supervision.*

| k | Original strict filter | Executable-filtered strict | Matched canonical oracle | Cleaned − original |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.465% | 1.574% | 4.883% | +0.109 pp |
| 2 | 2.220% | 2.346% | 7.241% | +0.126 pp |
| 4 | 3.248% | 3.261% | 9.623% | +0.012 pp |
| 8 | 4.406% | 4.126% | 11.805% | -0.280 pp |
| 16 | 5.490% | 4.915% | 13.466% | -0.575 pp |
| 32 | 6.346% | 5.713% | 14.580% | -0.633 pp |
| 64 | 6.949% | 6.454% | 15.432% | -0.494 pp |
| 128 | 7.500% | 7.000% | 16.000% | -0.500 pp |

Strict pass@1 improves by only 0.109 percentage points, closing 3.2% of the
original-to-oracle gap. The cleaned treatment is already worse by pass@8 and
ends 0.5 points below the original strict model at pass@128. Answer-only
performance also falls from 15.42%/61.0% pass@1/pass@128 under the original
strict model to 13.65%/57.0%, versus 20.87%/71.0% for the oracle.

The degradation is concentrated in forward-reverse behavior. Cleaning retains
26,707/48,225 (55.38%) reverse-mode training rows but 722,205/851,775 (84.79%)
normal-forward rows. On the balanced OP28 evaluation, reverse-mode answer
pass@1 falls from 24.35% to 20.98%, and length-limit terminations rise from
4.01% to 6.44%; the oracle reaches 28.09% with 2.31% length terminations. In
total, the cleaned model has 817 length terminations and 811 predictions with
no parseable answer, versus 518/512 for the original strict model and 308/331
for the oracle. Among normal-forward prompts, cleaning does improve strict
pass@1 from 2.901% to 3.117%, but strict pass@128 falls from 14.85% to 13.86%.

The conclusion is therefore negative: removing the identified semantic defects
does not explain the oracle advantage. The remaining gap is consistent with
the canonical target's deterministic reasoning style and much lower target
entropy, plus the cleaned treatment's 18% smaller token budget and stronger
reverse-mode curriculum bias. A matched-row-count resampling control would be
needed to separate those latter two effects, but the present clean filter
plainly does not match the oracle.

### Answer-correct versus strict-correct audit

The strict-filter model's OP28 pre-evaluation contains 25,600 trajectories:
3,565 have the exact final answer, but only 461 pass the dependency-graph
verifier. Among the 3,104 answer-correct/strict-wrong trajectories, all have a
dependency mismatch, 2,635 (84.9%) have at least one intermediate-value
mismatch, and 2,050 (66.0%) omit at least one gold node. These categories
overlap.

The gap is dominated by generation mode. Normal-forward trajectories have
6.91% answer pass@1 and 3.57% strict pass@1; 51.6% of their answer-correct
traces are strict-correct. Forward-reverse equation trajectories have 21.09%
answer pass@1 but zero strict-correct samples out of 12,672. The strict training
shards consequently contain only 17, 11, and 15 forward-reverse rows out of
50,000 at OP25, OP26, and OP27 respectively.

A stratified manual read of ten answer-correct/strict-wrong trajectories found
eight genuine reasoning failures, one internally inconsistent variable-reuse
case, and one clear verifier false negative:

| Sample | Mode/template | Manual finding |
| --- | --- | --- |
| `00ded...`, rank 2 | normal/zoo | Substitutes an equal-valued but wrong parent node. |
| `0b885...`, rank 0 | normal/movie | Uses the wrong same-valued source entity and adds an irrelevant node. |
| `35418...`, rank 8 | normal/school | Reassigns a previously defined letter; arithmetic works but symbol scope is inconsistent. |
| `9e4cc...`, rank 11 | normal/school | Omits a base node and asserts its downstream value directly. |
| `8d3b2...`, rank 14 | normal/movie | Multiple wrong intermediates cancel, preserving the final total. |
| `26f44...`, rank 14 | reverse/zoo | Writes `x+42=79`, then incorrectly asserts `x=1`, the gold answer. |
| `14459...`, rank 0 | reverse/movie | Semantically correct `x+31=33` solution rejected by letter-reuse leakage in the parser. |
| `73127...`, rank 96 | reverse/school | Changes `79` to `25` and known total `115` to `71`, then forces the gold answer. |
| `0080f...`, rank 61 | reverse/zoo | Wrong nodes and totals (`178` becomes `101`), followed by the gold answer. |
| `f36cb...`, rank 34 | reverse/movie | Turns the correct `x+80` equation into `x+44`, then still asserts `x=4`. |

Thus final-answer correctness is often produced by equal-value substitutions,
compensating errors, shortcuts, or answer anchoring. The released strict parser
also has a confirmed false-negative mechanism: its single-letter variable map
is global, so arbitrary reuse of a letter can leak unrelated dependencies into
an otherwise correct graph. The main strict track is preserved unchanged for
paper-faithful comparison, but its near-total removal of forward-reverse data
must be treated as a verifier-induced curriculum bias.

### Exponential replay ablation

To test whether uniform cumulative replay dilutes the newest frontier, fixed
OP11-25 strict data are reweighted with
`weight(op_i) = lambda ** (25 - op_i)`. The baseline training and held-out row
totals (750K/75K), fixed base initialization, 1,144 optimizer steps, optimizer,
scheduler, and minimum held-out-loss selection remain unchanged. This isolates
gradient recency but necessarily repeats recent trace rows; it does not add new
information.

| λ | Oldest/newest train rows | Unique/repeated train trace IDs | Natural one-epoch steps | SFT job |
| ---: | ---: | ---: | ---: | ---: |
| 0.95 | 34,074 / 69,870 | 678,455 / 71,545 | 1,168 | `9834296` |
| 0.90 | 21,606 / 94,445 | 607,275 / 142,725 | 1,194 | `9834297` |

Persistent CPU drivers `9834279` and `9834280` completed both audited datasets,
minimum-loss selections, and common OP25/OP26 evaluations. λ=0.95 logs to W&B
run `6qsnxv2u`; step 1,140 was selected at validation loss 0.03752742. λ=0.90
logs to `ziyqffhs`; step 1,140 was selected at 0.03226921. Validation losses
across λ are not directly comparable because each uses its matched reweighted
validation distribution.

| Replay | OP25 strict @1 / @128 | OP26 strict @1 / @128 |
| --- | ---: | ---: |
| Uniform baseline | 1.902% / 8.5% | 1.363% / 7.0% |
| λ=0.95 | 1.863% / 7.5% | 1.641% / 6.0% |
| λ=0.90 | 1.887% / 6.5% | 1.965% / 6.0% |

Neither decay improves strict accuracy on the OP25 training frontier. On the
held-out OP26 frontier, λ=0.95 raises strict pass@1 by 0.277 percentage points,
and λ=0.90 raises it by 0.602 points (+44% relative). Both reduce strict
pass@128 from 7% to 6%. Exponential replay therefore raises the probability of
a correct strict rollout on already-solvable problems, especially at λ=0.90,
but does not expand one-of-128 problem coverage in this run.

## Harmonic pass SFT from the pretrained base

This ablation tests whether difficulty-dependent SFT weighting improves
easy-to-hard generalization without iterative collection. The fixed pretrained
base generated 128 trajectories for each of 200 released problems at each of
OP11–14. Final-answer correctness defines the binary reward. The immutable pool
contains 102,400 trajectories and 47,500 positives: 21,868 at OP11, 13,311 at
OP12, 6,402 at OP13, and 5,919 at OP14.

Problems—not trajectories—are deterministically split within each operation:
160 problems per operation train and 40 validate. Consequently all 128
trajectories from one problem remain in exactly one split. Filtering produces
37,844 positive training trajectories (24,627,285 tokens) and 9,656 validation
trajectories (6,343,764 tokens), with zero problem overlap. The unweighted
baseline and all harmonic treatments use these exact same rows.

For each problem, `p_hat = correct_count / 128` is frozen at data-construction
time. A correct trajectory receives

`w_K(p_hat) = [1 + (1-p_hat) + ... + (1-p_hat)^(K-1)] / H_K`,

and incorrect trajectories are excluded. The sweep uses K=4, 8, 16, 32, and
64. The observed train-weight ranges are 0.480–1.898, 0.368–2.864,
0.296–4.465, 0.246–7.000, and 0.211–10.649 respectively. Both training and
held-out SFT loss use the same treatment-specific weights.

Every treatment, including the unweighted filtered-SFT baseline, resets to the
same pretrained base and trains for 248 optimizer steps with batch size 256,
sequence length 2,048, AdamW learning rate 1e-4, and the original Figure 3
cosine schedule. Validation and stable weight checkpoints occur every eight
steps, plus final step 248; the minimum configured held-out loss selects the
checkpoint. This yields 31 trained checkpoint candidates per run. All runs log
online to W&B.

The final benchmark is strictly out of distribution: OP15–18, 200 held-out
problems per operation, 128 sampled trajectories per problem. It reports both
answer-only and strict-graph pass@1,2,4,8,16,32,64,128 for the pretrained base,
unweighted SFT, and all five harmonic treatments.

A four-step K=16 smoke run completed as SLURM job `9872651` and W&B run
`4h9aidvl`. Weighted validation losses were finite at step 0 (0.09475763), step
2 (0.18528548), and step 4 (0.12865491); training reached 578K tokens/s with
4.4 GiB peak memory and no NaN losses.

All six full SFT runs completed without NaNs. Minimum held-out validation loss
selected baseline step 32 (0.09508730), K=4 step 24 (0.09536778), K=8 step 16
(0.09652019), K=16 step 16 (0.09809885), K=32 step 24 (0.09943316), and K=64
step 16 (0.10073516). Loss values select checkpoints only within their own
objective because each K changes the validation weights.
The W&B run IDs are `l6paike9` (baseline), `2kljho02` (K=4), `q6aq5541`
(K=8), `6zfr2oqx` (K=16), `b0nz7y4k` (K=32), and `11rwfktq` (K=64).

The complete OP15–18 unbiased answer-correctness results are:

![Harmonic weighted SFT OP15–18 pass@k and gains over unweighted SFT](figures/harmonic_sft_op15_18.svg)

| model | pass@1 | pass@2 | pass@4 | pass@8 | pass@16 | pass@32 | pass@64 | pass@128 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pretrained | 16.77% | 20.77% | 24.58% | 28.26% | 31.74% | 34.96% | 37.89% | 40.50% |
| unweighted SFT | 17.17% | 21.64% | 25.96% | 30.06% | 33.76% | 37.24% | 40.84% | 44.63% |
| harmonic K=4 | **17.97%** | 23.41% | 28.63% | 33.51% | 38.09% | 42.43% | 46.55% | 50.38% |
| harmonic K=8 | 17.14% | 22.33% | 27.16% | 31.58% | 35.62% | 39.40% | 43.26% | 47.25% |
| harmonic K=16 | 17.11% | 22.57% | 27.69% | 32.47% | 36.86% | 41.02% | 45.33% | 50.00% |
| harmonic K=32 | 17.78% | 23.40% | 28.78% | 33.82% | 38.57% | 43.00% | 46.96% | 50.63% |
| harmonic K=64 | 17.52% | **23.60%** | **29.37%** | **34.68%** | **39.60%** | **44.07%** | **48.06%** | **51.75%** |

Among completed treatments, K=4 has the best pass@1 and K=64 has the best
pass@2 through pass@128. Relative to unweighted SFT, K=64 changes pass@1 by
+0.35 percentage points and pass@128 by +7.13 points. Strict-graph pass@k is
zero for every completed model except K=16, whose strict pass@1 is 0.00195%
and strict pass@128 is 0.125%. Final-answer filtering therefore almost never
elicits the released dependency-graph format in this setting. The complete
sweep shows that harmonic weighting improves high-budget coverage substantially,
but larger objective K does not monotonically improve pass@1: K=4 gives the
largest pass@1 gain (+0.80 points over unweighted SFT), whereas K=64 gives the
largest pass@128 gain (+7.13 points).

Regenerate the figure from the preserved metric files with:

```bash
uv run user/tianhaowu/rsci/plot_harmonic_sft.py \
  --root /checkpoint/ram-h100-2/tianhaowu/rsci/harmonic-sft/base-op11-14-answer \
  --output user/tianhaowu/rsci/figures/harmonic_sft_op15_18.svg
```

## Strict-reward OP11–20 GRPO

The one-off RL baseline was submitted as SLURM job `9926135` at 18:15 UTC on
2026-08-03. It resets to the
released composition-pretrained base and samples a fresh, deduplicated,
balanced pool of 2,000 problems: 200 each at OP11–20, split approximately
equally across normal-forward/forward-reverse modes and across zoo, teacher,
and movie contexts. None of the released OP11–20 validation problems is used
for training.

Each training problem receives 128 on-policy rollouts. The sole optimization
reward is the released strict dependency-graph verifier; final-answer
correctness and the deterministic executable-strict grader have weight zero
and are diagnostics only. GRPO batches contain 512 trajectories (four problem
groups). The first run is provisioned for 500 updates at AdamW learning rate
1e-6, with checkpoints and held-out validation every 25 updates. The 500
updates consume 2,000 problem groups (four per update), one nominal pass over
the prompt pool before pipeline oversampling. Validation is
reported independently for each OP11–25 shard with one rollout per problem;
the selected checkpoints can subsequently use the existing 128-rollout
pass@k evaluator.

The deployment uses one eight-GPU trainer node plus four one-node inference
replicas. At most 8,192 trajectories, or 64 problem groups, remain in flight.
This is 16 concurrent 128-rollout groups per inference node, matching the
measured throughput optimum from job `9832143`. The environment, config, and
launch commands are documented in `configs/rl/README.md`.

CPU generation job `9920504` finalized the complete dataset in 6m22s. The
manifest records 2,000 accepted rows from 118,736 proposals, zero duplicate
acceptances, and train JSONL SHA-256
`68fbdb135ca9d48e26868ef627e722015946cce4aa67746721e592b8caada641`.
An independent post-generation audit found exactly 200 rows per operation,
2,000 unique prompt strings, zero exact prompt overlap with all 2,000 released
OP11–20 validation rows, and strict reward 1 for a canonical target sampled
from every operation. The same checks are now reproducibly stored in the
dataset's `audit.json`, with canonical strict verification expanded to all
2,000 rows. Context counts are 670/670/660 for movie/teacher/zoo;
mode counts are 1,010/990 for normal-forward/forward-reverse.

Validation spans OP11–25 with 200 held-out problems per operation. OP11–20 are
the released validation shards. OP21–25 reuse the immutable generated
frontier-extension shards (seed `20260802`, `generator_op_max=30`) rather than
creating a second evaluation distribution. A full prompt-keyed audit found
3,000/3,000 unique validation prompts, zero overlap with the 2,000 RL training
prompts, and 1,000/1,000 canonical OP21–25 completions passing the strict
verifier. Every generated file also matches the SHA-256 stored in its sidecar
manifest. Released row IDs are not globally unique, so prompt text is the
authoritative group and leakage key.

SLURM marks `9920504` failed with exit 127 after artifact finalization because
the running wrapper was edited to add unbuffered logging, shifting its final
continued shell line after the generator returned. The finalized manifest,
JSONL, and deduplication database were already atomically renamed and passed
the independent audit above; no RL job was submitted. The committed wrapper is
stable and passed both a miniature OP11–20 generation and `bash -n`.

The production launch passed prime-rl dry-run validation, materialized one
trainer node plus four independent inference replicas, and requested 40 H100s
under `h100_ram_high`. Its initial scheduler state is `PENDING (Priority)`.
Run health and OP11–25 validation measurements are tracked in the output
directory's `STATUS.md` and will be appended as the allocation progresses.
CPU monitor job `9927388` has an `after:9926135` dependency, so it begins with
the RL allocation, records the latest reward, strict per-operation validation,
KL, entropy, gradient norm, throughput, and log warnings each hour, then writes
a final entry and exits when the RL job terminates.

The first allocation failed before any trainer, inference server, rollout, or
W&B run started. Its generated SLURM script repeated `uv sync --all-extras` on
an H100 node; compute-node egress could not fetch metadata for the locked ARM
vLLM wheel, and job `9926135` exited 2 after 2m15s. The shared environment was
then verified by `uv sync --all-extras --locked` on the login side. Prime-RL's
SLURM config now exposes `sync_environment` (default `true`), and this RSCI run
sets it to `false`. A second dry-run verified that the generated script
activates the shared `.venv` without invoking `uv sync`; all 110 config tests
also pass. Replacement job `9931266` was submitted with unchanged model,
reward, data, and optimization settings. Monitor job `9931389` tracks the
replacement and checks terminal state every minute while appending metrics
hourly.

Replacement `9931266` exposed a second path through the same startup issue:
the top-level sync was gone, but nested `uv run` invocations implicitly synced
before launching trainer, inference, and orchestrator. The allocation was
cancelled after confirming zero rollouts, zero trainer steps, and no W&B
training run. With `sync_environment=false`, every bundled SLURM template now
exports `UV_NO_SYNC=1`, covering both explicit and implicit sync paths. The
regenerated production script contains one such export, no explicit `uv sync`,
and still contains the intended trainer, orchestrator, and inference commands;
all 110 config tests pass. Third attempt `9938021` and monitor `9938081` were
submitted with the experiment settings unchanged.

Attempt `9938021` then reached full trainer/orchestrator startup and launched
all 32 vLLM backends, each of which returned HTTP 200 from `/health`. The four
routers nevertheless saw all local workers as unavailable because the cluster
submission environment exports external HTTP proxies without a node-local
exception; direct requests succeeded while inherited-proxy requests did not.
The attempt was cancelled before any rollout or trainer step. The RSCI SLURM
pre-run command now builds `NO_PROXY`/`no_proxy` from every allocated hostname
plus localhost, preserving external proxy access for W&B. Fourth attempt
`9941560` and monitor `9941644` were submitted after a dry-run confirmed both
`UV_NO_SYNC=1` and the internal-host bypass in the generated script.

Attempt `9941560` confirmed the internal-host bypass: all four routers became
healthy and registered all 32 backends. Trainer and orchestrator then stalled
inside W&B initialization because the sandbox-only proxy itself is unreachable
from compute nodes. This matches all existing successful RSCI H100 launchers,
which unset inherited proxy variables and use direct compute egress. The
pre-run command now does the same while retaining the explicit internal
`NO_PROXY` list. Fifth attempt `9943759` and monitor `9943820` were submitted;
the experiment's model, data, strict reward, and optimization settings remain
unchanged across these startup-only retries.

Fifth attempt `9943759` is the first training attempt to pass startup. One
trainer, four routers, and all 32 inference workers became healthy; shared W&B
logging is online at
[`795781d17d14416290a22569cf808627`](https://meta-fair.wandb.io/ram/rsci/runs/795781d17d14416290a22569cf808627).
The trainer began from step zero, completed live NCCL policy broadcasts, and
produced checkpoints and validation artifacts at the configured interval. The
first 27 optimizer steps had zero rollout errors and zero truncations. The
repeated vLLM `RotaryEmbedding: Failed to load weights` warning is limited to a
non-persistent positional cache: all 13 state-dict shards are received, the
loader restores its existing cache, and `/update_weights` plus `/resume` return
HTTP 200 before inference continues.

The first post-training validation is encouraging but still preliminary. Each
cell below is strict pass@1 over the same 200 held-out prompts per operation,
sampled once at temperature 0.7. Prime-RL labels the second evaluation step 25
and logs policy version 24; the framework also persisted the scheduled
`step_25` checkpoint. The distinction is retained here rather than treating
the evaluation as necessarily following optimizer update 25.

![Strict-reward GRPO OP11–25 held-out validation](figures/rl_strict_op11_25.svg)

| operation | pretrained (step 0) | RL step 25 | change |
| --- | ---: | ---: | ---: |
| OP11 | 48.0% | 54.5% | +6.5 pp |
| OP12 | 22.0% | 40.0% | +18.0 pp |
| OP13 | 0.0% | 2.5% | +2.5 pp |
| OP14 | 0.0% | 0.0% | 0.0 pp |
| OP15 | 0.0% | 0.0% | 0.0 pp |
| OP16 | 0.0% | 0.0% | 0.0 pp |
| OP17 | 0.0% | 0.0% | 0.0 pp |
| OP18 | 0.0% | 0.0% | 0.0 pp |
| OP19 | 0.0% | 0.0% | 0.0 pp |
| OP20 | 0.0% | 0.0% | 0.0 pp |
| OP21 | 0.0% | 0.0% | 0.0 pp |
| OP22 | 0.0% | 0.0% | 0.0 pp |
| OP23 | 0.0% | 0.0% | 0.0 pp |
| OP24 | 0.0% | 0.0% | 0.0 pp |
| OP25 | 0.0% | 0.0% | 0.0 pp |
| OP11–25 micro-average | 4.67% | 6.47% | +1.80 pp |

Both evaluation directories contain exactly 3,000 rows: 200 for every OP11–25
shard. An artifact-level audit found zero scoring errors, zero length stops,
and zero disagreements between the recorded RL reward and
`strict_dependency_graph_reward`. Across the two evaluations, 1,135
trajectories had a correct final answer but an incorrect strict reasoning
graph; every one received reward zero. The OP13 result is the first nonzero
strict score beyond the pretrained frontier, while OP14–25 have not moved yet.
Because this is a single stochastic rollout per prompt, later checkpoints are
needed to separate persistent improvement from sampling noise.

Regenerate the figure from the saved rollout artifacts with:

```bash
uv run --no-sync user/tianhaowu/rsci/plot_rl_strict_eval.py \
  --rollouts-root /checkpoint/ram-h100-2/tianhaowu/rsci/rl/base-op11-20-strict-r128/run_default/rollouts \
  --output user/tianhaowu/rsci/figures/rl_strict_op11_25.svg
```

The 500-update phase completed every optimizer update, but its terminal
step-500 evaluation stalled partway through. The last complete validation is
therefore step 475: OP11 42.0%, OP12 39.5%, OP13 31.0%, OP14 24.5%, OP15
13.5%, OP16 2.5%, OP17 0.5%, and OP18–25 0.0% strict pass@1. The trainer had
written a complete step-500 checkpoint and stable inference weights, while the
orchestrator had not written matching step-500 progress. Job `9943759` and
monitor `9943820` were cancelled after the stalled evaluation remained
unchanged for more than an hour.

Training is extended to 10,000 updates without changing the model, data,
strict reward, rollout count, batch construction, optimizer, or validation
distribution. Prime-RL requires trainer and orchestrator to resume at the same
step, so the replacement uses the newest consistent checkpoint, step 475, and
repeats updates 475–499. The unmatched step-500 trainer and weight artifacts
are preserved under `archive/stalled-terminal-20260803` outside the numeric
checkpoint namespaces. Resume job `9972698` was submitted with a three-day
wall time, and four-day monitor job `9972839` tracks it with a 10,000-step
target. The figure above was regenerated from every complete evaluation
through step 475 before the resumed run began.

The replacement allocation began at 23:24 UTC on August 3 and restored both
trainer and orchestrator at step 475. All four routers and 32 inference workers
became healthy, shared W&B logging started in run
[`1a123a143941443cbeb2ab251241b1da`](https://meta-fair.wandb.io/ram/rsci/runs/1a123a143941443cbeb2ab251241b1da),
and optimization crossed the previous failure point. The step-500 evaluation
finished all 15 shards and 3,000 rollouts in about 20 seconds with zero rollout
errors or truncations. Matching trainer and orchestrator checkpoints, stable
inference weights, and 512 training rows were persisted at step 500; the run
then advanced through step 503 while both SLURM jobs remained healthy.

Step-500 strict pass@1 is OP11 44.5%, OP12 46.5%, OP13 36.5%, OP14 31.5%,
OP15 15.0%, OP16 5.0%, OP17 1.0%, and OP18–25 0.0%. Because evaluation and
weight broadcast overlap, these shards report mixed policy versions 499 and
500 and are labeled policy v499 in the log, consistent with the asynchronous
version convention described above. The figure now includes every complete
validation through step 500.

During the resumed pipeline warm-up, steps 493–496 reported 43–72% rollout
errors when requests older than the configured 16-step off-policy limit were
cancelled. This was transient queue cleanup rather than inference or verifier
failure: rollout error returned to 0% from step 497 onward, all router health
checks returned HTTP 200, and no traceback, OOM, NCCL failure, or NaN appeared
in the resumed trainer and orchestrator logs.

At 00:09 UTC on August 4, the resumed run was healthy at step 657. The latest
step had strict train reward 0.3145, 384/512 trainable trajectories, zero
rollout errors and truncations, mismatch KL 0.0002, and gradient norm 0.1982.
All four routers still returned HTTP 200. Step 650 has complete matching
trainer/orchestrator checkpoints, stable inference weights, 512 training rows,
and 200 held-out rows for every OP11–25 shard.

The train-reward and held-out trends through step 5625 are:

| eval step | preceding 25-step released-strict train reward | OP11–20 strict | OP15–20 strict | OP21–25 strict |
| ---: | ---: | ---: | ---: | ---: |
| 500 | 0.2414 | 18.00% | 3.50% | 0.00% |
| 525 | 0.1843 | 17.90% | 3.67% | 0.00% |
| 550 | 0.2148 | 19.60% | 3.83% | 0.00% |
| 575 | 0.2141 | 19.00% | 3.92% | 0.00% |
| 600 | 0.1791 | 18.60% | 4.33% | 0.00% |
| 625 | 0.2602 | 20.85% | 5.33% | 0.00% |
| 650 | 0.2957 | 20.90% | 6.25% | 0.00% |
| 675 | 0.2700 | 19.60% | 5.17% | 0.00% |
| 700 | 0.2548 | 19.90% | 6.33% | 0.00% |
| 725 | 0.2613 | 20.05% | 7.08% | 0.00% |
| 750 | 0.2734 | 20.10% | 7.50% | 0.00% |
| 775 | 0.3405 | 21.05% | 6.92% | 0.10% |
| 800 | 0.2100 | 22.40% | 8.67% | 0.00% |
| 825 | 0.3104 | 21.90% | 8.50% | 0.10% |
| 850 | 0.2813 | 22.00% | 8.92% | 0.00% |
| 875 | 0.2521 | 21.80% | 8.33% | 0.10% |
| 900 | 0.2310 | 20.35% | 8.00% | 0.10% |
| 925 | 0.2341 | 20.20% | 7.92% | 0.30% |
| 950 | 0.2616 | 19.45% | 6.75% | 0.00% |
| 975 | 0.3089 | 20.35% | 8.25% | 0.20% |
| 1000 | 0.2725 | 20.30% | 9.08% | 0.00% |
| 1025 | 0.3112 | 18.15% | 8.08% | 0.10% |
| 1050 | 0.2387 | 18.90% | 8.25% | 0.20% |
| 1075 | 0.2925 | 19.45% | 8.42% | 0.50% |
| 1100 | 0.3370 | 20.35% | 9.08% | 0.20% |
| 1125 | 0.2083 | 20.10% | 8.58% | 0.20% |
| 1150 | 0.2814 | 18.50% | 7.75% | 0.00% |
| 1175 | 0.2480 | 19.70% | 9.00% | 0.10% |
| 1200 | 0.3324 | 21.65% | 9.58% | 0.20% |
| 1225 | 0.3914 | 19.65% | 9.42% | 0.60% |
| 1250 | 0.2541 | 18.10% | 8.25% | 0.40% |
| 1275 | 0.3123 | 17.90% | 8.67% | 1.10% |
| 1300 | 0.3590 | 17.75% | 9.08% | 0.70% |
| 1325 | 0.2984 | 18.95% | 9.92% | 1.10% |
| 1350 | 0.2770 | 17.85% | 9.25% | 0.80% |
| 1375 | 0.3144 | 17.75% | 9.67% | 0.70% |
| 1400 | 0.3404 | 18.45% | 9.08% | 0.70% |
| 1425 | 0.3197 | 19.05% | 9.50% | 1.00% |
| 1450 | 0.2141 | 19.40% | 9.58% | 1.20% |
| 1475 | 0.3700 | 16.25% | 8.92% | 1.30% |
| 1500 | 0.3388 | 16.70% | 9.00% | 1.70% |
| 1525 | 0.2803 | 17.55% | 9.33% | 0.90% |
| 1550 | 0.3421 | 18.50% | 8.92% | 0.80% |
| 1575 | 0.2505 | 19.10% | 9.17% | 1.30% |
| 1600 | 0.3295 | 19.35% | 10.67% | 0.90% |
| 1625 | 0.3255 | 20.95% | 10.75% | 1.20% |
| 1650 | 0.3138 | 21.30% | 11.58% | 1.30% |
| 1675 | 0.2905 | 19.45% | 10.75% | 2.00% |
| 1700 | 0.3613 | 19.90% | 10.92% | 1.40% |
| 1725 | 0.3400 | 21.35% | 10.17% | 1.30% |
| 1750 | 0.3170 | 22.40% | 11.83% | 1.50% |
| 1775 | 0.3723 | 22.40% | 12.08% | 2.00% |
| 1800 | 0.2930 | 20.25% | 10.58% | 2.10% |
| 1825 | 0.3527 | 21.45% | 12.08% | 2.40% |
| 1850 | 0.3120 | 21.90% | 11.75% | 1.80% |
| 1875 | 0.3495 | 20.85% | 11.75% | 1.60% |
| 1900 | 0.3775 | 20.55% | 10.50% | 2.40% |
| 1925 | 0.4105 | 21.80% | 12.33% | 2.60% |
| 1950 | 0.3539 | 20.95% | 11.00% | 2.50% |
| 1975 | 0.3402 | 23.35% | 11.83% | 2.20% |
| 2000 | 0.3163 | 24.75% | 12.00% | 2.50% |
| 2025 | 0.3816 | 26.20% | 12.92% | 2.80% |
| 2050 | 0.3348 | 24.60% | 12.00% | 2.00% |
| 2075 | 0.4068 | 24.65% | 12.75% | 1.60% |
| 2100 | 0.3654 | 23.45% | 12.00% | 2.40% |
| 2125 | 0.3444 | 23.45% | 12.67% | 2.00% |
| 2150 | 0.3473 | 22.10% | 12.08% | 2.00% |
| 2175 | 0.2640 | 21.25% | 12.25% | 1.70% |
| 2200 | 0.3412 | 22.90% | 11.92% | 2.30% |
| 2225 | 0.3433 | 23.50% | 12.42% | 2.10% |
| 2250 | 0.3380 | 20.95% | 11.58% | 2.00% |
| 2275 | 0.3322 | 17.70% | 9.25% | 0.50% |
| 2300 | 0.3177 | 21.10% | 10.25% | 1.30% |
| 2325 | 0.3514 | 21.50% | 11.08% | 1.30% |
| 2350 | 0.3271 | 21.45% | 11.08% | 1.60% |
| 2375 | 0.4030 | 24.30% | 12.42% | 1.60% |
| 2400 | 0.3396 | 23.75% | 12.00% | 2.80% |
| 2425 | 0.3180 | 25.45% | 13.00% | 2.50% |
| 2450 | 0.3514 | 25.15% | 13.33% | 3.00% |
| 2475 | 0.4512 | 22.90% | 11.17% | 2.10% |
| 2500 | 0.2848 | 24.95% | 12.83% | 2.80% |
| 2525 | 0.4025 | 25.60% | 12.67% | 3.10% |
| 2550 | 0.3738 | 24.85% | 11.58% | 2.30% |
| 2575 | 0.3427 | 25.15% | 14.08% | 2.60% |
| 2600 | 0.3957 | 25.20% | 12.17% | 2.60% |
| 2625 | 0.3035 | 24.80% | 12.25% | 3.10% |
| 2650 | 0.3033 | 25.70% | 12.33% | 2.70% |
| 2675 | 0.4194 | 24.20% | 12.75% | 2.30% |
| 2700 | 0.3859 | 26.25% | 12.67% | 2.80% |
| 2725 | 0.3847 | 23.60% | 13.25% | 2.30% |
| 2750 | 0.3696 | 23.15% | 12.00% | 2.50% |
| 2775 | 0.3891 | 24.20% | 12.50% | 1.90% |
| 2800 | 0.3488 | 23.35% | 11.08% | 2.70% |
| 2825 | 0.4226 | 25.80% | 12.92% | 3.00% |
| 2850 | 0.3873 | 25.05% | 12.58% | 2.70% |
| 2875 | 0.3513 | 25.40% | 12.58% | 2.10% |
| 2900 | 0.3774 | 26.40% | 13.67% | 2.80% |
| 2925 | 0.3804 | 26.60% | 13.17% | 2.70% |
| 2950 | 0.3691 | 26.05% | 13.75% | 2.90% |
| 2975 | 0.4312 | 25.85% | 12.75% | 2.80% |
| 3000 | 0.3993 | 25.05% | 12.17% | 2.80% |
| 3025 | 0.4184 | 25.40% | 12.67% | 2.40% |
| 3050 | 0.4408 | 25.20% | 12.33% | 3.00% |
| 3075 | 0.3837 | 25.75% | 13.00% | 2.70% |
| 3100 | 0.4216 | 26.50% | 12.83% | 3.40% |
| 3125 | 0.3630 | 26.05% | 12.83% | 2.80% |
| 3150 | 0.4012 | 26.40% | 12.67% | 2.80% |
| 3175 | 0.4273 | 26.85% | 12.67% | 2.90% |
| 3200 | 0.3561 | 26.05% | 12.42% | 3.00% |
| 3225 | 0.3413 | 26.85% | 13.67% | 3.30% |
| 3250 | 0.3660 | 26.20% | 13.50% | 3.10% |
| 3275 | 0.3791 | 25.40% | 12.58% | 3.30% |
| 3300 | 0.3433 | 24.60% | 12.58% | 3.30% |
| 3325 | 0.3125 | 25.10% | 12.83% | 3.30% |
| 3350 | 0.3271 | 26.05% | 13.08% | 3.30% |
| 3375 | 0.3243 | 25.95% | 13.08% | 3.00% |
| 3400 | 0.3539 | 25.70% | 13.75% | 3.60% |
| 3425 | 0.3875 | 24.60% | 12.25% | 3.00% |
| 3450 | 0.4080 | 24.40% | 13.00% | 2.90% |
| 3475 | 0.3597 | 23.40% | 11.92% | 3.40% |
| 3500 | 0.3882 | 23.75% | 13.08% | 2.90% |
| 3525 | 0.4083 | 24.65% | 12.33% | 4.20% |
| 3550 | 0.4384 | 24.10% | 12.17% | 3.30% |
| 3575 | 0.4918 | 23.70% | 12.17% | 3.00% |
| 3600 | 0.3544 | 24.10% | 13.25% | 3.50% |
| 3625 | 0.3435 | 24.45% | 12.50% | 3.70% |
| 3650 | 0.4624 | 26.25% | 14.25% | 3.20% |
| 3675 | 0.3784 | 27.10% | 14.00% | 3.90% |
| 3700 | 0.3824 | 25.55% | 13.00% | 2.90% |
| 3725 | 0.4262 | 26.15% | 12.92% | 3.50% |
| 3750 | 0.3654 | 27.00% | 15.33% | 3.30% |
| 3775 | 0.3108 | 26.60% | 13.75% | 3.60% |
| 3800 | 0.3851 | 26.90% | 14.42% | 3.40% |
| 3825 | 0.4430 | 26.30% | 14.08% | 3.60% |
| 3850 | 0.4078 | 26.45% | 13.83% | 3.30% |
| 3875 | 0.4709 | 26.15% | 14.67% | 3.90% |
| 3900 | 0.3797 | 23.80% | 13.50% | 3.50% |
| 3925 | 0.3274 | 25.15% | 14.33% | 3.30% |
| 3950 | 0.4489 | 22.95% | 13.42% | 3.40% |
| 3975 | 0.4915 | 22.65% | 13.67% | 3.30% |
| 4000 | 0.2899 | 26.60% | 14.00% | 4.10% |
| 4025 | 0.3650 | 26.65% | 13.58% | 4.00% |
| 4050 | 0.4302 | 27.50% | 14.08% | 3.20% |
| 4075 | 0.4077 | 26.85% | 13.00% | 3.40% |
| 4100 | 0.4805 | 25.00% | 13.58% | 4.00% |
| 4125 | 0.4213 | 26.15% | 13.75% | 3.70% |
| 4150 | 0.3525 | 24.45% | 12.83% | 3.70% |
| 4175 | 0.3786 | 24.55% | 13.42% | 3.70% |
| 4200 | 0.5003 | 26.60% | 14.33% | 3.90% |
| 4225 | 0.4109 | 25.00% | 13.00% | 3.60% |
| 4250 | 0.3674 | 25.85% | 13.75% | 3.60% |
| 4275 | 0.3234 | 25.40% | 13.25% | 3.60% |
| 4300 | 0.3710 | 24.70% | 13.92% | 3.50% |
| 4325 | 0.3494 | 23.50% | 12.58% | 3.40% |
| 4350 | 0.4310 | 24.90% | 13.58% | 3.40% |
| 4375 | 0.4200 | 25.25% | 13.58% | 4.30% |
| 4400 | 0.4479 | 25.25% | 14.33% | 3.50% |
| 4425 | 0.3462 | 25.60% | 14.17% | 4.20% |
| 4450 | 0.4644 | 23.90% | 13.75% | 4.30% |
| 4475 | 0.4325 | 25.20% | 13.33% | 4.00% |
| 4500 | 0.3620 | 25.85% | 13.33% | 4.20% |
| 4525 | 0.3927 | 24.95% | 14.00% | 3.70% |
| 4550 | 0.3878 | 25.10% | 13.42% | 3.20% |
| 4575 | 0.3916 | 22.35% | 12.17% | 4.20% |
| 4600 | 0.4327 | 23.20% | 12.08% | 3.60% |
| 4625 | 0.4008 | 24.20% | 12.42% | 4.00% |
| 4650 | 0.3977 | 20.95% | 11.25% | 3.30% |
| 4675 | 0.3463 | 23.55% | 13.08% | 4.40% |
| 4700 | 0.5064 | 23.75% | 13.83% | 4.40% |
| 4725 | 0.3939 | 26.25% | 14.58% | 4.30% |
| 4750 | 0.4445 | 25.70% | 13.50% | 3.20% |
| 4775 | 0.3616 | 25.90% | 14.33% | 4.00% |
| 4800 | 0.3240 | 26.45% | 14.17% | 4.10% |
| 4825 | 0.3942 | 26.40% | 13.75% | 4.10% |
| 4850 | 0.4427 | 26.10% | 13.75% | 3.80% |
| 4875 | 0.3711 | 26.25% | 14.17% | 4.60% |
| 4900 | 0.4509 | 23.15% | 13.17% | 3.50% |
| 4925 | 0.4895 | 22.80% | 12.58% | 4.50% |
| 4950 | 0.4087 | 23.85% | 12.58% | 4.70% |
| 4975 | 0.3656 | 24.65% | 13.25% | 4.40% |
| 5000 | 0.3413 | 25.20% | 13.92% | 5.30% |
| 5025 | 0.4666 | 25.40% | 13.17% | 4.80% |
| 5050 | 0.4323 | 24.45% | 12.92% | 3.90% |
| 5075 | 0.3932 | 24.85% | 13.75% | 4.90% |
| 5100 | 0.5161 | 24.35% | 12.33% | 4.20% |
| 5125 | 0.4848 | 24.45% | 12.67% | 4.00% |
| 5150 | 0.3962 | 26.10% | 13.92% | 3.40% |
| 5175 | 0.3961 | 25.65% | 13.92% | 4.50% |
| 5200 | 0.3673 | 25.15% | 13.83% | 4.30% |
| 5225 | 0.4716 | 24.95% | 12.42% | 3.60% |
| 5250 | 0.3908 | 26.45% | 14.08% | 4.00% |
| 5275 | 0.4147 | 25.95% | 13.92% | 4.80% |
| 5300 | 0.4997 | 26.40% | 13.83% | 4.50% |
| 5325 | 0.4859 | 24.75% | 13.83% | 4.10% |
| 5350 | 0.3991 | 25.30% | 13.92% | 4.40% |
| 5375 | 0.3690 | 24.10% | 13.08% | 5.10% |
| 5400 | 0.5613 | 28.00% | 15.00% | 4.30% |
| 5425 | 0.4018 | 28.10% | 15.17% | 4.20% |
| 5450 | 0.3888 | 22.55% | 13.17% | 3.50% |
| 5475 | 0.3974 | 22.05% | 11.92% | 4.40% |
| 5500 | 0.4224 | 25.70% | 13.33% | 4.30% |
| 5525 | 0.3545 | 26.45% | 13.00% | 4.50% |
| 5550 | 0.3966 | 27.45% | 14.83% | 5.20% |
| 5575 | 0.4129 | 26.10% | 14.83% | 5.10% |
| 5600 | 0.4438 | 23.50% | 13.00% | 4.80% |
| 5625 | 0.4181 | 27.05% | 14.00% | 4.40% |

At step 650, strict pass@1 is OP11 52.0%, OP12 47.5%, OP13 38.5%, OP14
33.5%, OP15 18.5%, OP16 11.5%, OP17 5.5%, OP18 1.5%, OP19 0.5%, and OP20–25
0.0%. The improving OP15–19 frontier and higher recent train reward are
encouraging, but individual evaluations remain noisy single-rollout estimates:
Through step 650, OP11–20 aggregate accuracy had fluctuated between 17.9% and
20.9%, and no strict success had reached OP20 or OP21–25. The figure above now
contains every complete validation through step 5625. Step 675 temporarily
dipped to 19.60% over OP11–20 and 5.17% over OP15–20; step 700 rebounded to
19.90% and 6.33%, respectively. Step 725 then reached 20.05% over OP11–20 and
a new high of 7.08% over OP15–20. Step 750 continued the trend at 20.10% and
7.50%, with OP17 at 9.5% and OP19 at 2.0%. Step 775 had the highest 25-step
mean train reward so far, 0.3405, and a new OP11–20 high of 21.05%. Its
OP15–20 aggregate was 6.92%, while OP21 scored 0.5% for the first strict
success beyond the training range. The single OP21 trajectory derives the
three entity subgraphs in dependency order, obtains the exact answer 21, and
passes strict, executable-strict, and answer grading. It is a genuine result
but only 1/200, so it does not yet establish robust OP21 generalization. These
fluctuations support treating individual 200-prompt, single-rollout checkpoint
movements as noise unless they persist across multiple evaluations. Step 800
did not repeat the OP21 success, but it set new highs of 22.40% over OP11–20
and 8.67% over OP15–20. Its preceding mean train reward fell to 0.2100 despite
the held-out gain, demonstrating that the sampled 512-trajectory batch reward
is not a monotonic proxy for validation performance.

Step 825 returned to 21.90% over OP11–20 and 8.50% over OP15–20, with mean
train reward 0.3104. It also recorded one released-strict OP21 pass, but this
was not a genuine replication of step 775: executable grading catches two
compensating arithmetic errors, `26 + 19 = 51` followed by `51 + 57 = 102`.
The correct intermediate values are 45 and 102. The released graph verifier
accepts the dependency structure, node values, and final answer without
executing every intermediate equality chain.

This discrepancy is small but measurable rather than a verifier-hacking
collapse. At step 825, 439/3,000 trajectories pass released strict and
427/3,000 pass executable strict; all 12 disagreements are released-only
passes, so 97.27% of released-strict positives survive execution. For training
steps 801–825, released-strict reward averages 0.3104 and executable-strict
success averages 0.3018. Across the five latest 25-step windows, executable
precision among released-strict positives ranges from 94.47% to 99.17% with no
monotonic deterioration.

Step 850 remains at 22.00% over OP11–20 and sets a new OP15–20 high of 8.92%.
It contains the first strict OP20 success, 1/200, which also passes executable
strict and answer grading. Manual inspection confirms a coherent dependency
chain through Clearwater Bay and Shoreline City to the exact Oakbridge City
total of 49. This is a genuine first success on the hardest trained operation,
although one sample is not yet robust. The preceding train window has released
strict reward 0.2813 and executable-strict success 0.2790; 99.17% of released
positives survive execution. OP21–25 returned to zero.

Step 875 stays near the recent plateau at 21.80% over OP11–20 and 8.33% over
OP15–20. Both OP20 and OP21 score 0.5% and pass executable-strict grading. The
OP20 success repeats the same held-out problem as step 850 with an independently
sampled derivation. The OP21 success is a different held-out problem from the
genuine step-775 pass (dataset indices 90 and 26), so the model has now produced
two executable-strict OP21 successes on distinct prompts, separated by 100
updates. The rate remains only 1/200 at each checkpoint. The preceding train
window has released-strict reward 0.2521, executable-strict success 0.2415, and
95.79% executable precision among released positives.

Step 900 dips to 20.35% over OP11–20 and 8.00% over OP15–20, but broadens the
hardest successes. OP20 reaches 1.5% with executable-strict passes on three
distinct held-out prompts (indices 24, 43, and 71), rather than only repeating
the index-71 success from steps 850 and 875. OP21 again scores an
executable-strict 0.5% on index 90, repeating step 875; together with the
distinct index-26 pass at step 775, the model has solved two different OP21
prompts. The preceding train window has released-strict reward 0.2310,
executable-strict success 0.2255, 97.63% executable precision, zero rollout
errors, and 0.05% truncation.

Step 925 remains at 20.20% over OP11–20 and 7.92% over OP15–20 while OP21
rises to 1.5%. All three OP21 positives pass executable strict. They occur on
held-out indices 25, 90, and 140; indices 25 and 140 are new, while index 90
repeats the genuine steps 875 and 900 success. Including index 26 at step 775,
the model has now solved four distinct OP21 prompts with executable-strict
trajectories. The released-only, compensating-error index-24 case from step 825
is excluded. The preceding train window has released-strict reward 0.2341,
executable-strict success 0.2263, 96.70% executable precision, 2.54% transient
off-policy cancellation errors, and 0.16% truncation.

Step 950 does not retain the step-925 OP21 spike: OP11–20 falls to 19.45%,
OP15–20 to 6.75%, and OP21–25 to 0.00%. This supports treating the 1.5%
OP21 checkpoint result as a genuine but low-probability frontier crossing, not
stable pass@1 generalization. OP20 remains nonzero at 0.5% on held-out index
92, a fifth distinct executable-strict OP20 prompt after indices 24, 43, 52,
and 71. Manual inspection confirms its complete arithmetic chain from the
Festival de Clairmont total of 7 through the Rêves de Belleville total of 25
to the exact Cinéma de Montreval answer 35. Across the full step-950
evaluation, 389/3,000 trajectories pass released strict and 378/3,000 pass
executable strict, for 97.17% executable precision among released positives.
The preceding train window has released-strict reward 0.2616,
executable-strict success 0.2584, 98.75% executable precision, 0.62% transient
off-policy cancellation errors, and 0.02% truncation.

Step 975 rebounds to 20.35% over OP11–20 and 8.25% over OP15–20. OP21
returns to 1.0% with executable-strict passes on indices 90 and 140. Both are
previously solved prompts, so this adds replication rather than frontier
breadth; their response hashes differ from step 925 and manual inspection
confirms two newly sampled, internally consistent derivations to answers 41
and 37. OP20 similarly scores 1.0% on previously solved indices 52 and 71.
Across the full evaluation, 409/3,000 trajectories pass released strict and
401/3,000 pass executable strict, for 98.04% executable precision. The
preceding train window has released-strict reward 0.3089, executable-strict
success 0.2964, 95.95% executable precision, 1.76% transient off-policy
cancellation errors, and 0.02% truncation.

Step 1300 confirms that OP23 is not a one-checkpoint event. OP23 reaches 1.0%
on repeated index 165 and new index 19; index 165 has a different response hash
from step 1275, and manual inspection confirms both trajectories execute
cleanly. OP22 reaches 1.5% and adds index 22, while OP21 adds index 78. The
cumulative executable-strict breadth is now 10 distinct OP20 prompts, 12 OP21
prompts, eight OP22 prompts, and two OP23 prompts. OP11–20 remains low at
17.75%, OP15–20 is 9.08%, and OP21–25 is 0.70%. Across the full evaluation,
362/3,000 trajectories pass released strict and 349/3,000 pass executable
strict, for 96.41% executable precision. The preceding train window has
released-strict reward 0.3590, executable-strict success 0.3472, 96.71%
executable precision, 0.96% transient off-policy cancellation errors, and
0.02% truncation. Consecutive OP23 checkpoints with both replication and new
prompt coverage are substantially stronger evidence than the initial 1/200
crossing, although absolute pass@1 remains only 1.0%.

Step 1325 keeps OP21–25 at its 1.10% high and sets a new OP15–20 high of
9.92%. OP21 reaches 3.0% and adds two manually verified prompts, indices 92
and 157, bringing cumulative OP21 breadth to 14. OP22 reaches 2.0% on four
known prompts. OP23 index 165 passes for a third consecutive checkpoint with a
third distinct response hash; cumulative OP23 breadth remains two prompts.
The cumulative executable-strict counts are therefore 10 distinct OP20
prompts, 14 OP21 prompts, eight OP22 prompts, and two OP23 prompts. OP11–20 is
18.95%. Across the full evaluation, 390/3,000 trajectories pass released
strict and 367/3,000 pass executable strict, for 94.10% executable precision.
The preceding train window has released-strict reward 0.2984,
executable-strict success 0.2863, 95.92% executable precision, 1.15% transient
off-policy cancellation errors, and 0.12% truncation. Three consecutive OP23
checkpoints establish persistent prompt-specific generalization, although not
yet broad or high-probability OP23 performance.

Step 1350 keeps broad OP20–22 coverage but OP23 returns to zero. OP20, OP21,
and OP22 each add one manually verified prompt (indices 80, 94, and 98),
raising cumulative executable-strict breadth to 11, 15, and nine distinct
prompts, respectively; OP23 remains at two. OP11–20 is 17.85%, OP15–20 is
9.25%, and OP21–25 is 0.80%. Across the full evaluation, 365/3,000
trajectories pass released strict and 349/3,000 pass executable strict, for
95.62% executable precision. The preceding train window has released-strict
reward 0.2770, executable-strict success 0.2685, 96.95% executable precision,
1.43% transient off-policy cancellation errors, and 0.27% truncation.

Response length is also becoming a measurable hard-task constraint. From step
1200 to step 1350, OP21–25 mean completion length rises from 407 to 444 tokens,
the 95th percentile rises from 572 to 628, and truncation rises from 0.5% to
1.9%. Across all OP11–25 prompts, truncation rises from 0.23% to 1.07%. These
rates are not yet large enough to explain the frontier variance, but the fixed
2,048-token sequence budget is now a potential bottleneck worth tracking.

Step 1375 restores OP23 to 1.0% on repeated index 165 and new index 32. The new
trajectory executes coherently to answer 16, and index 165 has now passed at
four checkpoints with four distinct response hashes. Cumulative
executable-strict breadth rises to three OP23 prompts, while OP20, OP21, and
OP22 remain at 11, 15, and nine prompts. OP11–20 is 17.75%, OP15–20 is 9.67%,
and OP21–25 is 0.70%. Across the full evaluation, 362/3,000 trajectories pass
released strict and 341/3,000 pass executable strict, for 94.20% executable
precision. The preceding train window has released-strict reward 0.3144,
executable-strict success 0.3045, 96.84% executable precision, 0.84% transient
off-policy cancellation errors, and 0.24% truncation. Evaluation truncation
falls from 1.07% at step 1350 to 0.20%, so the length-pressure spike did not
persist monotonically, although the longer-run completion-length trend still
warrants monitoring.

Step 1400 holds OP21–25 at 0.70% while broadening the genuine frontier. New
executable-strict trajectories on OP20 index 70, OP22 index 142, and OP23 index
91 were manually checked: each follows the stated dependencies, executes all
arithmetic consistently, and reaches its gold answer. OP23 index 165 also
passes for a fifth checkpoint with a fifth distinct response hash. Cumulative
executable-strict breadth is now 12 distinct OP20 prompts, 15 OP21 prompts, 10
OP22 prompts, and four OP23 prompts. OP11–20 is 18.45% and OP15–20 is 9.08%.
Across the full evaluation, 376/3,000 trajectories pass released strict and
359/3,000 pass executable strict, for 95.48% executable precision. The
preceding train window has released-strict reward 0.3404, executable-strict
success 0.3333, 97.91% executable precision, 1.52% transient off-policy
cancellation errors, and 0.16% truncation. Evaluation truncation is 0.30%, so
the earlier length-pressure spike remains non-monotonic.

Step 1425 raises OP11–20 to 19.05%, OP15–20 to 9.50%, and OP21–25 to 1.00%.
OP23 reaches 1.0% on repeated index 165 and new index 4. Manual inspection of
index 4 confirms a coherent dependency chain and exact arithmetic to answer
29; index 165 passes for a sixth checkpoint with a sixth distinct response
hash. Cumulative executable-strict breadth is now 12 distinct OP20 prompts, 15
OP21 prompts, 10 OP22 prompts, and five OP23 prompts. Across the full
evaluation, 391/3,000 trajectories pass released strict and 369/3,000 pass
executable strict, for 94.37% executable precision. The 22 released-only
positives are concentrated in OP11–17; 15 are forward-reverse trajectories.
Their deterministic-grader issues include 13 solver-equation mismatches and
seven ordinary equality mismatches, with overlapping undefined-symbol and
unexpected-node errors. All 10 released-strict OP21–23 positives also pass
executable strict, so this verifier gap does not create the observed frontier
gain. The preceding train window has released-strict reward 0.3197,
executable-strict success 0.3140, 98.22% executable precision, 0.99% transient
off-policy cancellation errors, and 0.02% truncation. Evaluation truncation is
0.10%. A mismatch-KL spike to 0.0087 at step 1401 recovers to 0.0008 at step
1402 and at most 0.0018 thereafter in the window, with no persistent stability
failure.

Step 1450 raises OP11–20 to 19.40%, OP15–20 to 9.58%, and OP21–25 to a new
high of 1.20%. OP21 adds indices 149 and 153; manual inspection confirms both
are coherent, executable derivations to answers 46 and 98. Cumulative
executable-strict breadth is now 12 distinct OP20 prompts, 17 OP21 prompts, 10
OP22 prompts, and five OP23 prompts. OP23 indices 32 and 165 both repeat with
new response hashes; index 165 has now passed at seven checkpoints with seven
distinct samples. Across the full evaluation, 400/3,000 trajectories pass
released strict and 386/3,000 pass executable strict, for 96.50% raw
executable precision. All 12 released-strict OP21–23 positives also pass
executable strict, so the new frontier coverage is not a verifier artifact.
Evaluation truncation is 0.13%.

The preceding train window drops to released-strict reward 0.2141 and raw
executable-strict success 0.1974, or 92.23% raw executable precision, with
1.74% transient off-policy cancellation errors and 0.06% truncation. This gap
is highly concentrated: 180/213 released-only rows come from two 128-rollout
prompt groups. OP13 forward-reverse task 511 contributes 116 genuinely invalid
rows. They replace the correct `9*x + 3 + 30*x + 9 = 39*x + 12` with false
equalities such as `33*x + 18`; because the solution happens to be `x = 1`,
the corrupted expression still reaches 51 and the released graph verifier
awards reward one. This is a real verifier failure that can reinforce bad
algebra. OP11 task 86 contributes another 64 disagreements that are instead
false negatives from the executable grader: the model correctly derives the
problem-stated extra fact `public highschool in Hawkesbury = 36`, but the gold
solution omits that unnecessary node and the grader labels it unexpected.
Counting those correct extra-node trajectories raises executable success to
0.2024 and precision to 94.56%. Excluding both concentrated groups, raw
executable precision is 98.68%, so this window is prompt-composition driven
rather than a broad verifier collapse. Mismatch KL remains at most 0.0006 and
gradient norm at most 0.3152 throughout the window.

Step 1475 records the first genuine OP24 success, extending the observed
frontier four operations beyond the OP11–20 training range. OP24 index 24
passes released strict, executable strict, and manual inspection: it derives
the Northwood total 12, the West Sahara total 30, and the exact Verdi answer
41 without an arithmetic inconsistency. New executable-strict prompts also
appear at OP20 index 12 and OP22 index 91. Cumulative breadth is now 13
distinct OP20 prompts, 17 OP21 prompts, 11 OP22 prompts, five OP23 prompts, and
one OP24 prompt. OP23 index 165 passes at an eighth checkpoint with an eighth
distinct response hash. OP21–25 reaches a new high of 1.30%, but OP11–20 drops
to 16.25% and OP15–20 to 8.92%; the OP24 result is only 1/200 and the
in-distribution dip needs replication before either is treated as stable.
Across the full evaluation, 338/3,000 trajectories pass released strict and
328/3,000 pass executable strict, for 97.04% raw executable precision. All 13
released-strict OP21–24 positives also pass executable strict, and evaluation
truncation is 0.13%.

The preceding train window has released-strict reward 0.3700,
executable-strict success 0.3561, 96.24% raw executable precision, 2.38%
transient off-policy cancellation errors, and 0.32% truncation. The problematic
step-1439 OP13 task 511 and the executable-grader false-negative task 86 do not
recur. Instead, 136/178 released-only rows are concentrated in four different
forward-reverse prompt groups, and 155/178 gaps are forward-reverse overall;
the dominant diagnostics remain solver-equation and equality mismatches.
Gradient norm spikes to 0.7396 at step 1451 and 0.9242 at step 1474 while
mismatch KL remains at most 0.0007. By step 1480, gradient norm is back to
0.1347 and mismatch KL to 0.0000, so neither spike persists.

Step 1500 does not replicate OP24, but OP21–25 rises to another new high of
1.70% through broader OP21–23 coverage. New manually checked,
executable-strict trajectories appear at OP20 index 50, OP21 index 17, OP22
indices 144 and 162, and OP23 index 70. Each follows its dependency chain and
executes to the gold answer. Cumulative breadth is now 14 distinct OP20
prompts, 18 OP21 prompts, 13 OP22 prompts, six OP23 prompts, and one OP24
prompt. OP11–20 remains depressed at 16.70% and OP15–20 is 9.00%. Across the
last two checkpoints, OP11–14 averages 27.75% over 1,600 trajectories, versus
33.33% over the preceding three checkpoints' 2,400 trajectories, a 5.58-point
drop. Because OP15–20 remains near 9% while the OOD frontier improves, this is
consistent with an easy-task/frontier tradeoff rather than uniform collapse.
Filtering all-zero-advantage groups removes most direct consolidation pressure
from easy, all-pass prompts and is one plausible mechanism, but these results
do not by themselves establish causality. Across the full step-1500
evaluation, 351/3,000 trajectories pass released strict and 332/3,000 pass
executable strict, for 94.59% raw executable precision. All 17 released-strict
OP21–23 positives also pass executable strict. Evaluation truncation is 0.37%.

The preceding train window has released-strict reward 0.3388,
executable-strict success 0.3179, 93.84% raw executable precision, 1.76%
transient off-policy cancellation errors, and 0.03% truncation. Of 267 raw
released-only rows, 93 come from OP14 task 765 and are executable-grader false
negatives: the model correctly derives the problem-stated extra fact `adult
crow in Mayer Aquarium = 20`, which the gold solution omits. Counting those
valid rows raises executable precision to 95.99%. Another 75 rows come from
OP14 forward-reverse task 706 and contain genuine algebra errors. Outside
these two concentrated groups, raw executable precision is 97.62%. Mismatch
KL spikes transiently to 0.0031–0.0058 at steps 1483–1487 with gradient norm
at most 0.1675, then recovers to 0.0004 by step 1495; maximum gradient norm in
the full window is 0.3277.

Step 1525 partially recovers OP11–20 to 17.55% and OP15–20 to 9.33%, while
OP21–25 falls to 0.90%. OP11–14 is 29.88%, above 27.25% and 28.25% at steps
1475 and 1500 but still below the 33.33% average over steps 1400–1450. No new
executable-strict prompt breadth appears: OP20, OP21, and OP22 retain
cumulative counts of 14, 18, and 13, while OP23 and OP24 both score zero and
remain at six and one cumulative prompts. The first OP24 crossing is therefore
genuine but still rare rather than stable pass@1 generalization. Across the
full evaluation, 360/3,000 trajectories pass released strict and 346/3,000
pass executable strict, for 96.11% raw executable precision. All nine
released-strict OP21–22 positives pass executable strict, and evaluation
truncation is 0.07%.

The preceding train window has released-strict reward 0.2803,
executable-strict success 0.2735, 97.58% raw executable precision, 1.30%
transient off-policy cancellation errors, and 0.14% truncation. Mismatch KL
stays at most 0.0008 and gradient norm at most 0.2399, with no stability spike.

Step 1550 recovers OP11–20 to 18.50%. OP11–14 is back to 32.88%, close to its
33.33% step-1400–1450 average, so the preceding three-checkpoint easy-task dip
has not persisted as a permanent regression. OP15–20 is 8.92% and OP21–25 is
0.80%. OP22 adds one manually checked executable-strict prompt, index 14,
whose complete chain reaches answer 52; OP23 repeats known index 32 and OP24
again scores zero. Cumulative breadth is 14 distinct OP20 prompts, 18 OP21
prompts, 14 OP22 prompts, six OP23 prompts, and one OP24 prompt. Across the
full evaluation, 378/3,000 trajectories pass released strict and 368/3,000
pass executable strict, for 97.35% raw executable precision. All eight
released-strict OP21–23 positives pass executable strict, and evaluation
truncation is 0.17%.

The preceding train window has released-strict reward 0.3421,
executable-strict success 0.3245, 94.86% raw executable precision, 0.50%
transient off-policy cancellation errors, and 0.02% truncation. OP12 task 277
accounts for 55/225 raw disagreements, but these are executable-grader false
negatives: the model correctly derives the problem-stated extra Clearwater Bay
regional-medical-school fact that the gold solution omits. Counting those
valid trajectories raises executable precision to 96.12%. Genuine gaps remain
concentrated in forward-reverse algebra, led by 83 rows from task 599 and 34
from task 597. Stability is more variable than in the prior window: gradient
norm reaches 1.1983 at step 1528 and mismatch KL reaches 0.0164 at step 1547.
By step 1559, mismatch KL is back to 0.0000 and gradient norm to 0.3125. There
is still no NaN, OOM, or persistent divergence, but these recurring transients
warrant continued monitoring.

Step 1575 reaches 19.10% on OP11–20, completing the recovery from the
step-1475–1525 dip. OP15–20 is 9.17% and OP21–25 rebounds to 1.30%. OP21 adds
new index 145; manual inspection confirms a coherent chain through Mayer
Aquarium and Jefferson Circus to the exact Hamilton Farm answer 17. OP23
index 165 passes for a ninth checkpoint with a ninth distinct response hash,
while OP24 remains zero for a fourth checkpoint after its first crossing.
Cumulative breadth is 14 distinct OP20 prompts, 19 OP21 prompts, 14 OP22
prompts, six OP23 prompts, and one OP24 prompt. Across the full evaluation,
395/3,000 trajectories pass released strict and 384/3,000 pass executable
strict, for 97.22% raw executable precision. All 13 released-strict OP21–23
positives also pass executable strict, and evaluation truncation is 0.17%.

The preceding train window has released-strict reward 0.2505,
executable-strict success 0.2472, 98.66% raw executable precision, 1.62%
transient off-policy cancellation errors, and 0.01% truncation. Mismatch KL
stays at most 0.0022 and gradient norm reaches 0.9893 transiently; by step 1579
they are back to 0.0001 and 0.0913, respectively.

Step 1600 sets a new OP15–20 strict high of 10.67%, above the prior 9.92% at
step 1325, while OP11–20 reaches 19.35%. OP20 itself is 4.5%, matching OP19,
and OP21–25 is 0.90%. OP22 adds new index 134; manual inspection confirms its
complete South Zoo–Mayer Aquarium–Hamilton Farm chain to answer 23. OP23 and
OP24 both score zero. Cumulative executable-strict breadth is 14 distinct OP20
prompts, 19 OP21 prompts, 15 OP22 prompts, six OP23 prompts, and one OP24
prompt. Across the full evaluation, 396/3,000 trajectories pass released
strict and 382/3,000 pass executable strict, for 96.46% raw executable
precision. All nine released-strict OP21–22 positives also pass executable
strict, and evaluation truncation is 0.23%.

The preceding train window has released-strict reward 0.3295,
executable-strict success 0.3248, 98.58% raw executable precision, 1.55%
transient off-policy cancellation errors, and 0.03% truncation. Mismatch KL
reaches 0.0078 and gradient norm 0.6348 transiently; by step 1606 they have
returned to 0.0006 and 0.1862, respectively, without divergence.

Step 1625 raises OP11–20 to 20.95%, its highest value since step 1200, and
sets another OP15–20 high at 10.75%. OP21–25 is 1.20%. OP23 reaches 1.5% on
three known prompts, indices 4, 32, and 165, providing replication without new
breadth. OP24 is zero for a sixth consecutive checkpoint after its single
step-1475 crossing. Cumulative executable-strict breadth remains 14 distinct
OP20 prompts, 19 OP21 prompts, 15 OP22 prompts, six OP23 prompts, and one OP24
prompt. Across the full evaluation, 431/3,000 trajectories pass released
strict and 419/3,000 pass executable strict, for 97.22% raw executable
precision. All 12 released-strict OP21–23 positives also pass executable
strict, and evaluation truncation is 0.33%.

The preceding train window has released-strict reward 0.3255,
executable-strict success 0.3230, 99.23% raw executable precision, 1.53%
transient off-policy cancellation errors, and 0.08% truncation. Mismatch KL
stays at most 0.0038 and gradient norm at most 0.3603, with no persistent
stability issue.

Step 1650 improves OP11–20 again to 21.30% and sets a third consecutive
OP15–20 high at 11.58%. OP21–25 is 1.30%. OP21 adds new index 71; manual
inspection confirms a coherent Glenfield City–Westhaven City–Brightford chain
to answer 28. OP23 repeats known index 70, while OP24 remains zero. Cumulative
executable-strict breadth is 14 distinct OP20 prompts, 20 OP21 prompts, 15
OP22 prompts, six OP23 prompts, and one OP24 prompt. Across the full
evaluation, 439/3,000 trajectories pass released strict and 428/3,000 pass
executable strict, for 97.49% raw executable precision. All 13
released-strict OP21–23 positives also pass executable strict, and evaluation
truncation is 0.13%.

The preceding train window has released-strict reward 0.3138,
executable-strict success 0.3059, 97.49% raw executable precision, 0.96%
transient off-policy cancellation errors, and 0.08% truncation. The isolated
16.8% rollout-error spike at step 1637 returns to zero by step 1646. Mismatch
KL stays at most 0.0003 and gradient norm at most 0.2940, so the window is
otherwise stable.

Step 1675 sets a new OP21–25 strict high of 2.00%. OP21 reaches 5.0%, OP22
3.5%, and OP23 1.5%. New OP21 index 136 and OP23 index 151 both pass
executable strict and manual inspection: their dependency chains execute to
answers 20 and 74 without arithmetic errors. Cumulative breadth is now 14
distinct OP20 prompts, 21 OP21 prompts, 15 OP22 prompts, seven OP23 prompts,
and one OP24 prompt. OP24 remains zero for an eighth consecutive checkpoint
after its isolated crossing. OP15–20 remains strong at 10.75%, while OP11–20
fluctuates down to 19.45%. Across the full evaluation, 409/3,000 trajectories
pass released strict and 399/3,000 pass executable strict, for 97.56% raw
executable precision. All 20 released-strict OP21–23 positives also pass
executable strict, and evaluation truncation is 0.17%.

The preceding train window has released-strict reward 0.2905,
executable-strict success 0.2872, 98.84% raw executable precision, 2.03%
transient off-policy cancellation errors, and 0.02% truncation. Mismatch KL
stays at most 0.0007 and gradient norm at most 0.3184.

Step 1700 keeps OP15–20 elevated at 10.92%, with OP11–20 at 19.90% and
OP21–25 at 1.40%. The step-1675 2.00% OOD spike does not fully persist, but
new executable-strict prompts broaden OP20 and OP22: indices 86 and 10 are
manually coherent chains to answers 16 and 28. OP23 repeats known index 91 and
OP24 remains zero. Cumulative breadth is now 15 distinct OP20 prompts, 21 OP21
prompts, 16 OP22 prompts, seven OP23 prompts, and one OP24 prompt. Across the
full evaluation, 412/3,000 trajectories pass released strict and 399/3,000
pass executable strict, for 96.84% raw executable precision. All 14
released-strict OP21–23 positives also pass executable strict, and evaluation
truncation is 0.30%.

The preceding train window has released-strict reward 0.3613,
executable-strict success 0.3505, 97.04% raw executable precision, 0.30%
transient off-policy cancellation errors, and 0.01% truncation. Mismatch KL
stays at most 0.0006 and gradient norm at most 0.5254.

Step 1725 keeps OP11–20 strong at 21.35% and OP15–20 at 10.17%, while
OP21–25 is 1.30%. OP23 adds new index 79; manual inspection confirms its
Clearwater Bay–Riverton City–Ruby Bay chain executes to answer 40. Cumulative
executable-strict breadth is now 15 distinct OP20 prompts, 21 OP21 prompts, 16
OP22 prompts, eight OP23 prompts, and one OP24 prompt. OP24 remains zero for
all 10 checkpoints after its step-1475 crossing. Across the full evaluation,
440/3,000 trajectories pass released strict and 429/3,000 pass executable
strict, for 97.50% raw executable precision. All 13 released-strict OP21–23
positives also pass executable strict.

Evaluation truncation rises to 0.73%: it is highest on OP24 at 3.0%, followed
by OP22 at 2.0% and OP20 at 1.5%, with smaller counts on OP13 and OP15–19.
This is another sign that the fixed 2,048-token sequence budget increasingly
pressures the longer tasks, although the rate remains volatile across
checkpoints.

The preceding train window has released-strict reward 0.3400,
executable-strict success 0.3312, 97.43% raw executable precision, 3.18%
transient off-policy cancellation errors, and 0.01% truncation. Rollout errors
spike to 25.9% at step 1723 but return to zero by step 1731. Mismatch KL reaches
0.0049 and gradient norm 0.7593 transiently; by step 1731 they are 0.0002 and
0.0459, respectively.

Step 1750 is the strongest checkpoint so far. OP11–20 reaches 22.40%, tying
the run's all-time high from step 800, and OP15–20 sets a new high of 11.83%.
OP21–25 is 1.50%. New OP21 index 150 and OP23 index 100 both pass executable
strict and manual inspection, with complete chains to answers 54 and 53.
Cumulative breadth is now 15 distinct OP20 prompts, 22 OP21 prompts, 16 OP22
prompts, nine OP23 prompts, and one OP24 prompt. OP24 remains zero for all 11
checkpoints after its isolated crossing. Across the full evaluation,
463/3,000 trajectories pass released strict and 451/3,000 pass executable
strict, for 97.41% raw executable precision. All 15 released-strict OP21–23
positives also pass executable strict, and evaluation truncation is 0.40%.

The preceding train window has released-strict reward 0.3170,
executable-strict success 0.3152, 99.46% raw executable precision, 1.02%
transient off-policy cancellation errors, and 0.04% truncation. Mismatch KL
spikes to 0.0092 at step 1740 but recovers to 0.0003 by step 1749; maximum
gradient norm is 0.3956, with no persistent instability.

Step 1775 confirms rather than merely spikes the recent gains. OP11–20 again
reaches its 22.40% all-time high, OP15–20 sets another high at 12.08%, and
OP21–25 ties its 2.00% high. OP22 adds new indices 80 and 141, and OP23 adds
index 141; manual inspection confirms all three dependency chains and exact
answers. Cumulative executable-strict breadth is now 15 distinct OP20 prompts,
22 OP21 prompts, 18 OP22 prompts, 10 OP23 prompts, and one OP24 prompt. OP24
remains zero for all 12 checkpoints after its isolated crossing. Across the
full evaluation, 468/3,000 trajectories pass released strict and 455/3,000
pass executable strict, for 97.22% raw executable precision. All 20
released-strict OP21–23 positives also pass executable strict, and evaluation
truncation is 0.37%.

The preceding train window has released-strict reward 0.3723,
executable-strict success 0.3564, 95.74% raw executable precision, 1.39%
transient off-policy cancellation errors, and 0.05% truncation. The 203 raw
verifier disagreements are concentrated: 164 come from three prompt groups,
and 147 are forward-reverse trajectories; equality and solver-equation
mismatches dominate. Mismatch KL stays at most 0.0006 and gradient norm at
most 0.3128.

Step 1800 produces the first genuine OP25 success, extending the observed
frontier five operations beyond the OP11–20 training range. OP25 index 28
passes released strict, executable strict, and manual inspection: the trace
derives totals 1, 8, and 10 before reaching the exact Verdi answer 15. New
manually verified OP21 index 100 and OP23 index 23 also broaden coverage.
OP21–25 sets a new high of 2.10%; OP11–20 is 20.25% and OP15–20 is 10.58%.
Cumulative executable-strict breadth is now 15 distinct OP20 prompts, 23 OP21
prompts, 18 OP22 prompts, 11 OP23 prompts, one OP24 prompt, and one OP25
prompt. Across the full evaluation, 426/3,000 trajectories pass released
strict and 409/3,000 pass executable strict, for 96.01% raw executable
precision. All 21 released-strict OP21–25 positives also pass executable
strict.

Evaluation truncation rises to 0.80% and is strongly length-dependent: OP25
has 11/200 truncated responses (5.5%), while OP22 and OP24 are each 1.5% and
OP20 is 1.0%. The fixed 2,048-token sequence budget is now a material OP25
constraint and may understate its attainable accuracy.

The preceding train window has released-strict reward 0.2930,
executable-strict success 0.2816, 96.11% raw executable precision, 1.41%
transient off-policy cancellation errors, and 0.17% truncation. Mismatch KL
stays at most 0.0007 and gradient norm at most 0.6078. The single-batch train
truncation spike to 1.6% at step 1789 falls back to zero by step 1804.

Step 1825 sets another OP21–25 high at 2.40% and replicates OP24 on a second
distinct prompt. OP24 index 13 passes released strict, executable strict, and
manual inspection with a coherent Taylor–Northwood–Golden Banana chain to
answer 53. OP15–20 ties its 12.08% high and OP11–20 is 21.45%. New manually
checked trajectories add OP20 indices 44, 82, and 101, OP21 index 79, and OP23
indices 84 and 142. Cumulative executable-strict breadth rises to 18 distinct
OP20 prompts, 24 OP21 prompts, 18 OP22 prompts, 13 OP23 prompts, two OP24
prompts, and one OP25 prompt. OP25 itself returns to zero. Across the full
evaluation, 453/3,000 trajectories pass released strict and 438/3,000 pass
executable strict, for 96.69% raw executable precision. All 24 released-strict
OP21–24 positives also pass executable strict, and evaluation truncation is
0.33%.

The preceding train window has released-strict reward 0.3527,
executable-strict success 0.3462, 98.16% raw executable precision, 1.20%
transient off-policy cancellation errors, and 0.43% truncation. The high
window truncation is dominated by step 1813: one OP14 forward-reverse group
contributes 37/42 truncated rows and one OP20 forward-reverse group contributes
five. Both groups have zero strict successes and are removed by the
zero-advantage filter. Mismatch KL stays at most 0.0022 and gradient norm at
most 0.5672.

Step 1850 keeps the improved regime: OP11–20 is 21.90%, OP15–20 is 11.75%,
and OP21–25 is 1.80%. OP24 succeeds on new index 152, a third distinct prompt;
manual inspection confirms its Oakridge Riverside–Cedar Valley–Beverly Forest
chain to answer 35. New manually checked trajectories also add OP20 indices
13, 21, and 62, OP21 index 160, and OP23 index 147. Cumulative
executable-strict breadth reaches 21 distinct OP20 prompts, 25 OP21 prompts,
18 OP22 prompts, 14 OP23 prompts, three OP24 prompts, and one OP25 prompt.
OP25 itself remains zero. Across the full evaluation, 456/3,000 trajectories
pass released strict and 444/3,000 pass executable strict, for 97.37% raw
executable precision. All 18 released-strict OP21–24 positives also pass
executable strict, and evaluation truncation is 0.33%.

The preceding train window has released-strict reward 0.3120,
executable-strict success 0.2986, 95.69% raw executable precision, 0.90%
transient off-policy cancellation errors, and 0.16% truncation. The step-1838
22.4% cancellation spike returns to zero by step 1848. Mismatch KL stays at
most 0.0008 and gradient norm at most 0.3674.

Step 1875 remains above the earlier regime but retreats from the recent
frontier peak: OP11–20 is 20.85%, OP15–20 is 11.75%, and OP21–25 is 1.60%.
OP20 adds new index 97, whose manually inspected Maple Creek–Cedar Valley–Pine
Ridge chain reaches answer 48. OP24 and OP25 both return to zero. Cumulative
executable-strict breadth is now 22 distinct OP20 prompts, 25 OP21 prompts, 18
OP22 prompts, 14 OP23 prompts, three OP24 prompts, and one OP25 prompt. Across
the full evaluation, 433/3,000 trajectories pass released strict and
423/3,000 pass executable strict, for 97.69% raw executable precision. All 16
released-strict OP21–23 positives also pass executable strict, and evaluation
truncation is 0.30%.

The preceding train window has released-strict reward 0.3495,
executable-strict success 0.3359, 96.09% raw executable precision, 1.95%
transient off-policy cancellation errors, and 0.06% truncation. Mismatch KL
stays at most 0.0012 and gradient norm at most 0.3792.

Step 1900 ties the 2.40% OP21–25 high and strengthens the evidence for OP24
generalization. OP24 reaches 1.0% on known index 24 and new index 78; manual
inspection confirms the new trace's complete Ruby Bay–Riverton City–Shoreline
City chain to answer 83. OP11–20 is 20.55% and OP15–20 is 10.50%. OP22 also
adds new index 79. Cumulative executable-strict breadth is now 22 distinct
OP20 prompts, 25 OP21 prompts, 19 OP22 prompts, 14 OP23 prompts, four OP24
prompts, and one OP25 prompt. OP25 returns to zero. Across the full
evaluation, 435/3,000 trajectories pass released strict and 429/3,000 pass
executable strict, for 98.62% raw executable precision. All 24 released-strict
OP21–24 positives also pass executable strict, and evaluation truncation is
0.10%.

The preceding train window has released-strict reward 0.3775,
executable-strict success 0.3615, 95.76% raw executable precision, zero logged
off-policy cancellation errors, and 0.09% truncation. Mismatch KL stays at
most 0.0011 and gradient norm reaches 0.7852 transiently without divergence.

Step 1925 sets new highs of 12.33% on OP15–20 and 2.60% on OP21–25, while
OP11–20 is 21.80%. OP21 alone reaches 6.5%, OP22 reaches 4.0%, and OP23
reaches 2.5%. No new executable-strict prompt breadth appears, so this
checkpoint's frontier gain is replication and higher sampled success
probability on known prompts rather than coverage expansion. Cumulative
breadth remains 22 distinct OP20 prompts, 25 OP21 prompts, 19 OP22 prompts, 14
OP23 prompts, four OP24 prompts, and one OP25 prompt. OP24 and OP25 both score
zero. Across the full evaluation, 462/3,000 trajectories pass released strict
and 447/3,000 pass executable strict, for 96.75% raw executable precision. All
26 released-strict OP21–23 positives also pass executable strict, and only
1/3,000 evaluation trajectories truncates.

The preceding train window has the highest documented released-strict reward
so far at 0.4105, with executable-strict success 0.4007 and 97.62% raw
executable precision. Logged off-policy cancellation errors average 0.86%; no
saved train trajectory truncates. Mismatch KL stays at most 0.0002 and
gradient norm at most 0.1681, making this one of the most stable windows.

Step 1950 keeps the beyond-training-range aggregate near its peak: OP11–20 is
20.95%, OP15–20 is 11.00%, and OP21–25 is 2.50%. New manually inspected,
executable-consistent successes appear on OP22 index 139 and OP23 index 89,
expanding cumulative executable-strict breadth to 22 distinct OP20 prompts,
25 OP21 prompts, 20 OP22 prompts, 15 OP23 prompts, four OP24 prompts, and one
OP25 prompt. OP24 and OP25 both score zero at this checkpoint. Across the full
evaluation, 444/3,000 trajectories pass released strict and 433/3,000 pass
executable strict, for 97.52% raw executable precision. All 25 released-strict
OP21–23 positives also pass executable strict, and evaluation truncation is
0.30%.

The preceding train window has released-strict reward 0.3539,
executable-strict success 0.3381, and 95.54% raw executable precision. Logged
off-policy cancellation errors average 0.95%, while only 0.01% of saved train
trajectories truncate. Mismatch KL stays at most 0.0024 and gradient norm at
most 0.4371 without persistent instability.

Step 1975 raises OP11–20 to a new run high of 23.35%, with OP15–20 at 11.83%
and OP21–25 at 2.20%. New OP23 index 137 passes both strict graders; manual
inspection confirms its complete Maple Creek–Pine Ridge–Beverly Forest chain
to the exact answer 59. Cumulative executable-strict breadth is therefore 22
distinct OP20 prompts, 25 OP21 prompts, 20 OP22 prompts, 16 OP23 prompts, four
OP24 prompts, and one OP25 prompt. OP24 and OP25 both score zero. Across the
full evaluation, 489/3,000 trajectories pass released strict and 482/3,000
pass executable strict, for 98.57% raw executable precision. All 22
released-strict OP21–23 positives also pass executable strict. Evaluation
truncation is 0.07%, with no rollout errors.

The preceding train window has released-strict reward 0.3402,
executable-strict success 0.3341, and 98.23% raw executable precision. Logged
off-policy cancellation errors average 0.87%; saved-train truncation is 0.02%.
Mismatch KL stays at most 0.0006, while gradient norm briefly reaches 0.6608
at step 1974 and immediately remains finite without divergence.

Step 2000 raises OP11–20 to another run high of 24.75%, while OP15–20 reaches
12.00% and OP21–25 returns to 2.50%. OP21, OP22, and OP23 score 6.0%, 4.0%,
and 2.5%, respectively; every one of these 25 released-strict OOD positives
also passes executable strict. OP24 and OP25 remain zero, and this checkpoint
adds no new OP20–25 prompt coverage. Cumulative executable-strict breadth stays
at 22 distinct OP20 prompts, 25 OP21 prompts, 20 OP22 prompts, 16 OP23 prompts,
four OP24 prompts, and one OP25 prompt. Across the full evaluation, 520/3,000
trajectories pass released strict and 514/3,000 pass executable strict, for
98.85% raw executable precision. Evaluation truncation is 0.13%, with no
rollout errors.

The preceding train window has released-strict reward 0.3163,
executable-strict success 0.3000, and 94.86% raw executable precision. Logged
off-policy cancellation errors average 1.00%; saved-train truncation is 0.02%.
Mismatch KL stays at most 0.0018. Gradient norm briefly reaches 0.9871 at step
1979, then returns to ordinary values without NaNs or divergence.

Step 2025 is the strongest checkpoint so far across all three aggregates:
OP11–20 reaches 26.20%, OP15–20 reaches 12.92%, and OP21–25 reaches 2.80%.
OP24 alone scores 1.5% on known index 13 and new indices 21 and 163. Manual
inspection confirms both new traces: index 21 completes the Rêves de
Belleville–Cinéma de Montreval–Festival de Clairmont chain to answer 36, and
index 163 completes the Maple Creek–Oakridge Riverside–Cedar Valley chain to
answer 58. New manually checked executable-strict coverage also appears at
OP20 index 26 and OP22 index 152. Cumulative breadth reaches 23 distinct OP20
prompts, 25 OP21 prompts, 21 OP22 prompts, 16 OP23 prompts, six OP24 prompts,
and one OP25 prompt. OP25 remains zero. Across the full evaluation, 552/3,000
trajectories pass released strict and 539/3,000 pass executable strict, for
97.64% raw executable precision. All 28 released-strict OP21–24 positives pass
executable strict. Evaluation truncation is 0.40%, with no rollout errors.

The preceding train window has released-strict reward 0.3816,
executable-strict success 0.3624, and 94.96% raw executable precision. Logged
off-policy cancellation errors average 2.65%; saved-train truncation is 0.06%.
Mismatch KL stays at most 0.0013 and gradient norm at most 0.3686, with no
persistent instability.

Step 2050 retreats from the step-2025 peak but remains in the stronger recent
regime: OP11–20 is 24.60%, OP15–20 is 12.00%, and OP21–25 is 2.00%. New
executable-strict coverage appears at OP20 indices 72 and 102 and OP21 index 3.
Manual inspection confirms all three complete arithmetic chains to answers 66,
15, and 41, respectively. OP24 replicates known index 24 at 0.5%, while OP25
remains zero. Cumulative breadth reaches 25 distinct OP20 prompts, 26 OP21
prompts, 21 OP22 prompts, 16 OP23 prompts, six OP24 prompts, and one OP25
prompt. Across the full evaluation, 512/3,000 trajectories pass released
strict and 504/3,000 pass executable strict, for 98.44% raw executable
precision. All 20 released-strict OP21–24 positives pass executable strict.
Evaluation truncation is 0.73%, with no rollout errors.

The preceding train window has released-strict reward 0.3348,
executable-strict success 0.3300, and 98.55% raw executable precision. Logged
off-policy cancellation errors average 1.25%; saved-train truncation is 0.10%.
Mismatch KL stays at most 0.0014. Gradient norm briefly reaches 0.6710 at step
2038 and then returns without NaNs or divergence.

Step 2075 holds the in-range aggregate at 24.65% and raises OP15–20 to 12.75%,
but OP21–25 falls to 1.60%. OP21, OP22, and OP23 score 3.0%, 4.0%, and 1.0%;
OP24 and OP25 both score zero. No new OP20–25 prompt coverage appears, so
cumulative executable-strict breadth remains 25 distinct OP20 prompts, 26 OP21
prompts, 21 OP22 prompts, 16 OP23 prompts, six OP24 prompts, and one OP25
prompt. Across the full evaluation, 509/3,000 trajectories pass released
strict and 501/3,000 pass executable strict, for 98.43% raw executable
precision. All 16 released-strict OP21–23 positives pass executable strict.
Evaluation truncation is 0.43%, with no rollout errors.

The preceding train window has released-strict reward 0.4068,
executable-strict success 0.4005, and 98.46% raw executable precision. Logged
off-policy cancellation errors average 1.22%; saved-train truncation is 0.12%.
Mismatch KL briefly reaches 0.0088 at step 2064 but returns to zero on the next
three steps; gradient norm stays at most 0.5386. There are no NaNs or persistent
instability.

Step 2100 has OP11–20 at 23.45%, OP15–20 at 12.00%, and OP21–25 at 2.40%.
New executable-strict coverage appears at OP22 index 147 and OP24 index 69.
Manual inspection confirms the complete Bundle Ranch–South Zoo–Jefferson
Circus chain to answer 100 and Oakbridge City–Ruby Bay–Shoreline City chain to
answer 41, respectively. OP24 also replicates known index 24, while OP25
remains zero. Cumulative breadth reaches 25 distinct OP20 prompts, 26 OP21
prompts, 22 OP22 prompts, 16 OP23 prompts, seven OP24 prompts, and one OP25
prompt. Across the full evaluation, 493/3,000 trajectories pass released
strict and 485/3,000 pass executable strict, for 98.38% raw executable
precision. All 24 released-strict OP21–24 positives pass executable strict.
Evaluation truncation is 0.17%, with no rollout errors.

The preceding train window has released-strict reward 0.3654,
executable-strict success 0.3604, and 98.63% raw executable precision. Logged
off-policy cancellation errors average 1.46%, driven by a one-step 36.5% spike
at step 2086; saved train rows contain no errors and only 0.03% truncation.
Mismatch KL reaches 0.0045 at step 2085, then falls to 0.0001 or below over
steps 2096–2099 and zero at step 2100. Gradient norm stays at most 0.3133.

Step 2125 keeps OP11–20 at 23.45%, raises OP15–20 to 12.67%, and has
OP21–25 at 2.00%. New executable-strict coverage appears at OP20 index 37 and
OP22 index 155. Manual inspection confirms the complete Festival de
Saint-Rivage–Festival Lumière de Valmont–Festival de Clairmont chain to answer
46 and Pine Ridge–Oakridge Riverside–Maple Creek chain to answer 66,
respectively. OP24 and OP25 both score zero. Cumulative breadth reaches 26
distinct OP20 prompts, 26 OP21 prompts, 23 OP22 prompts, 16 OP23 prompts, seven
OP24 prompts, and one OP25 prompt. Across the full evaluation, 489/3,000
trajectories pass released strict and 483/3,000 pass executable strict, for
98.77% raw executable precision. All 20 released-strict OP21–23 positives pass
executable strict. Evaluation truncation is 0.10%, with no rollout errors.

The preceding train window has released-strict reward 0.3444,
executable-strict success 0.3323, and 96.48% raw executable precision. Logged
off-policy cancellation errors average 2.77%, driven by a one-step 26.4% spike
at step 2103; saved train rows contain no errors and 0.18% truncation. Mismatch
KL stays at most 0.0017 and gradient norm at most 0.2395.

Step 2150 falls to 22.10% on OP11–20 while retaining 12.08% on OP15–20 and
2.00% on OP21–25. New executable-strict OP20 index 99 is manually verified as
a coherent Evervale City–Westhaven City–Hawkesbury chain to answer 25. OP24
and OP25 both score zero. Cumulative breadth reaches 27 distinct OP20 prompts,
26 OP21 prompts, 23 OP22 prompts, 16 OP23 prompts, seven OP24 prompts, and one
OP25 prompt. Across the full evaluation, 462/3,000 trajectories pass released
strict and 450/3,000 pass executable strict, for 97.40% raw executable
precision. All 20 released-strict OP21–23 positives pass executable strict.
Evaluation truncation is 0.37%, with no rollout errors.

The preceding train window has released-strict reward 0.3473 but only 0.3179
executable-strict success, lowering raw executable precision to 91.52%.
Deterministic re-grading confirms this is a real released-verifier weakness:
all canonical solutions pass executable strict, while all 377 released-only
rows contain at least one concrete issue. Five prompts account for 339/377
(89.9%) of the disagreements. The dominant issue codes are
`solver_equation_mismatch` on 300 rows and `equation_mismatch` on 259 rows,
with overlap; one row also has `undefined_symbol`. Manually inspected examples
include `66 + 13 = 67` followed by `67 + 5 = 84` and corrupted symbolic
equations whose final integer coincides with the gold answer. This is recurrent
reward hacking by the released strict verifier, not executable-grader false
rejection. Logged off-policy cancellation errors average 0.72%; saved-train
truncation is 0.02%. Mismatch KL stays at most 0.0006 and gradient norm at most
0.3517.

Step 2175 falls to 21.25% on OP11–20 while holding 12.25% on OP15–20 and
1.70% on OP21–25. It produces the second distinct executable-strict OP25
success observed in the run: new index 72. Manual inspection confirms the full
Westhaven City total of 13, Brightford total of 32, and Hawkesbury total of 69.
OP24 scores zero. Cumulative breadth remains 27 distinct OP20 prompts, 26 OP21
prompts, 23 OP22 prompts, 16 OP23 prompts, and seven OP24 prompts, while OP25
expands to two prompts. Across the full evaluation, 442/3,000 trajectories pass
released strict and 436/3,000 pass executable strict, for 98.64% raw executable
precision. All 17 released-strict OP21–23 and OP25 positives pass executable
strict. Evaluation truncation is 0.23%, with no rollout errors.

The preceding train window has released-strict reward 0.2640 and
executable-strict success 0.2487, for 94.20% raw executable precision. All 196
released-only rows fail deterministic execution while every corresponding
canonical solution passes; two prompts account for 154/196 (78.6%). Issue-code
counts are 189 `equation_mismatch`, 63 `solver_equation_mismatch`, two
`undefined_symbol`, and one `expression_syntax`, with overlap. This confirms
continued released-verifier reward hacking, although less concentrated than in
the step-2150 window. Logged rollout errors are zero and saved-train truncation
is 0.09%. Mismatch KL stays at most 0.0007 and gradient norm at most 0.4476.

Step 2200 rebounds to 22.90% on OP11–20 and 2.30% on OP21–25, with OP15–20
at 11.92%. OP24 replicates known index 69 at 0.5%; OP25 returns to zero. No new
OP20–25 prompt coverage appears, so cumulative executable-strict breadth
remains 27 distinct OP20 prompts, 26 OP21 prompts, 23 OP22 prompts, 16 OP23
prompts, seven OP24 prompts, and two OP25 prompts. Across the full evaluation,
481/3,000 trajectories pass released strict and 471/3,000 pass executable
strict, for 97.92% raw executable precision. All 23 released-strict OP21–24
positives pass executable strict. Evaluation truncation is 0.03%, with no
rollout errors.

The preceding train window has released-strict reward 0.3412 and
executable-strict success 0.3352, restoring raw executable precision to 98.24%.
Released-only rows fall from 196 in the previous window to 77; the largest
single prompt contributes 23 rather than 109, so verifier-error concentration
has receded substantially. Logged rollout errors are zero and saved-train
truncation is 0.05%. Mismatch KL briefly reaches 0.0034 at step 2200, then
returns to 0.0001 at step 2201 and zero by step 2204; gradient norm stays at
most 0.3598 within the audited window.

Step 2225 improves OP11–20 to 23.50% and OP15–20 to 12.42%, with OP21–25 at
2.10%. OP24 replicates known index 24 at 0.5%; OP25 remains zero. No new
OP20–25 prompt coverage appears, so cumulative executable-strict breadth stays
at 27 distinct OP20 prompts, 26 OP21 prompts, 23 OP22 prompts, 16 OP23 prompts,
seven OP24 prompts, and two OP25 prompts. Across the full evaluation,
491/3,000 trajectories pass released strict and 479/3,000 pass executable
strict, for 97.56% raw executable precision. All 21 released-strict OP21–24
positives pass executable strict. Evaluation truncation is 0.20%, with no
rollout errors.

The preceding train window has released-strict reward 0.3433 and
executable-strict success 0.3323, for 96.81% raw executable precision.
Released-only rows rise from 77 to 140 but remain below the preceding verifier
spikes; one prompt contributes 95/140 (67.9%). Deterministic re-grading again
finds every canonical solution valid and every released-only model row
problematic, with 128 `equation_mismatch`, 131 `solver_equation_mismatch`, two
`expression_syntax`, and one `undefined_symbol` issue-code occurrences, with
overlap. Logged off-policy cancellation errors average 0.86%; saved rows have
no errors and 0.03% truncation. Mismatch KL stays at most 0.0004 and gradient
norm at most 0.4881.

Step 2250 falls to 20.95% on OP11–20, 11.58% on OP15–20, and 2.00% on
OP21–25. New executable-strict OP21 index 74 is manually verified as a
coherent Evervale City–Westhaven City chain to answer 26, expanding cumulative
OP21 breadth to 27 prompts. The sole released-strict OP25 positive, index 18,
is invalid: it writes `60 + 18 = 90` and then `90 + 30 = 108`, using two
arithmetic errors to force the gold answer. OP25 executable strict is therefore
zero. Other cumulative breadth remains 27 distinct OP20 prompts, 23 OP22
prompts, 16 OP23 prompts, seven OP24 prompts, and two OP25 prompts. Across the
full evaluation, 439/3,000 trajectories pass released strict and 424/3,000 pass
executable strict, for 96.58% raw executable precision. Evaluation truncation
is 0.23%, with no rollout errors.

The preceding train window has released-strict reward 0.3380 and
executable-strict success 0.3258, for 96.37% raw executable precision. Of 157
released-only rows, 147 have direct arithmetic, syntax, undefined-symbol, or
solver-equation errors. The other 10 come from one prompt and are rejected only
as `unexpected_node`; manual inspection shows the irrelevant extra node is
semantically wrong, substituting the Beverly Forest owl count for the stated
Maple Creek eagle count. The discrepancy therefore remains substantive rather
than an executable-grader false reject. Logged off-policy cancellation errors
average 1.18%; saved rows have no errors and 0.02% truncation. Mismatch KL stays
at most 0.0015 and gradient norm briefly reaches 0.6143 without divergence.

Step 2275 is a noisy dip to 17.70% on OP11–20, 9.25% on OP15–20, and 0.50%
on OP21–25. The five released-strict frontier positives—two OP21 and one each
on OP22, OP23, and OP24—all pass executable strict, while OP25 is zero. All
repeat previously solved prompts, so cumulative executable-strict breadth
remains 27 distinct OP20 prompts, 27 OP21 prompts, 23 OP22 prompts, 16 OP23
prompts, seven OP24 prompts, and two OP25 prompts. Across the full evaluation,
359/3,000 trajectories pass released strict and 346/3,000 pass executable
strict, for 96.38% raw executable precision. Evaluation truncation is 0.47%,
with no rollout errors.

The preceding train window has released-strict reward 0.3322 and
executable-strict success 0.3187, for 95.93% raw executable precision. All 173
released-only rows are reproduced by deterministic re-grading, all 2,000
canonical solutions pass, and the issue-code counts are 142
`equation_mismatch`, 142 `solver_equation_mismatch`, one `expression_syntax`,
and 19 `unexpected_node`, with overlap. The three most concentrated prompts
account for 98/173 rows. Logged off-policy cancellation errors average 0.64%
and peak transiently at 16.1% on step 2257; saved rows have no errors and 0.03%
truncation. Mismatch KL briefly reaches 0.0073 at step 2264 and gradient norm
reaches 0.7762 at step 2256, then recover to 0.0006 and 0.0531 at step 2275.
The step-2275 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 2300 rebounds to 21.10% on OP11–20, 10.25% on OP15–20, and 1.30% on
OP21–25. OP22 index 87 is a new executable-strict prompt: manual inspection
confirms the Clearwater Bay total of 40, Shoreline City total of 15, and
Riverton City components 15, 36, and 12 summing coherently to answer 63. This
expands cumulative OP22 breadth to 24 prompts; other cumulative breadth stays
at 27 distinct OP20 prompts, 27 OP21 prompts, 16 OP23 prompts, seven OP24
prompts, and two OP25 prompts. Across the full evaluation, 435/3,000
trajectories pass released strict and 424/3,000 pass executable strict, for
97.47% raw executable precision. Evaluation truncation is 0.40%, with no
rollout errors.

The preceding train window has released-strict reward 0.3177 and
executable-strict success 0.3038, for 95.62% raw executable precision. All 178
released-only rows agree under deterministic re-grading, all canonical
solutions pass, and the issue-code counts are 49 `equation_mismatch`, 129
`solver_equation_mismatch`, and 16 `unexpected_node`, with overlap. One prompt
contributes 110/178 rows. Logged off-policy cancellation errors average 2.84%
and peak transiently at 47.0% on step 2289; none survive into the saved rows,
whose truncation rate is 0.14%. Mismatch KL briefly reaches 0.0111 at step 2280
and gradient norm stays at most 0.3131, then both return to 0.0000 and 0.0077
at step 2300. The step-2300 trainer and orchestrator checkpoints, eight
distributed trainer shards, stable inference weights, 512 training rows, and
all 3,000 evaluation rows are complete.

Step 2325 improves to 21.50% on OP11–20 and 11.08% on OP15–20 while holding
OP21–25 at 1.30%. New executable-strict OP21 index 19 is manually verified as
a coherent Verdi–Taylor–Golden Banana chain: the respective intermediate
totals are 28 and 41, and the final Taylor value is 43. Cumulative OP21 breadth
therefore reaches 28 prompts; breadth stays at 27 OP20 prompts, 24 OP22
prompts, 16 OP23 prompts, seven OP24 prompts, and two OP25 prompts. Across the
full evaluation, 443/3,000 trajectories pass released strict and 429/3,000
pass executable strict, for 96.84% raw executable precision. Evaluation
truncation is 0.57%, with no rollout errors.

On OP20 alone, step 2325 scores 2.50%, below the matched strict-filter OP20
SFT checkpoint's 4.734% unbiased strict pass@1 by 2.234 points. The last ten
RL checkpoints average 4.30% released strict and 4.25% executable strict on
OP20, close to the SFT result, while the best single RL checkpoint reaches
6.50% at step 1825. The individual RL evaluations use only one stochastic
draw per 200 prompts, whereas the matched SFT estimate uses 128 draws per
prompt; the selected RL maximum is therefore too noisy to establish
superiority. Across OP11–20, step 2325 nevertheless reaches 21.50%, versus
10.02% for the strict-filter OP20 checkpoint.

The preceding train window has released-strict reward 0.3514 and
executable-strict success 0.3427, for 97.51% raw executable precision. All 112
released-only rows agree under deterministic re-grading, all canonical
solutions pass, and the issue-code counts are 103
`solver_equation_mismatch`, 27 `equation_mismatch`, one `expression_syntax`,
three `undefined_symbol`, and one `unexpected_node`, with overlap. One prompt
contributes 68/112 rows. Logged off-policy cancellation errors average 1.14%
and peak transiently at 15.2% on step 2315; saved rows have no errors and
0.24% truncation. Mismatch KL stays at most 0.0033 and gradient norm at most
0.3754, ending at 0.0000 and 0.2596. The step-2325 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2350 remains stable at 21.45% on OP11–20 and 11.08% on OP15–20 while
OP21–25 rises to 1.60%. OP20 rebounds to 4.50%, only 0.234 points below the
matched strict-filter OP20 checkpoint's 4.734% pass@1 and well within the
sampling noise of this checkpoint's single rollout per prompt. New
executable-strict OP21 index 67 is manually verified through Ruby Bay and
Riverton City totals 8 and 26 to Clearwater Bay answer 29. New OP22 index 33
is also coherent, deriving Taylor and West Sahara totals 14 and 24 before the
Golden Banana answer 32. Cumulative breadth reaches 29 OP21 prompts and 25
OP22 prompts; it stays at 27 OP20 prompts, 16 OP23 prompts, seven OP24 prompts,
and two OP25 prompts. Across the full evaluation, 445/3,000 trajectories pass
released strict and 435/3,000 pass executable strict, for 97.75% raw
executable precision. Evaluation truncation is 0.27%, with no rollout errors.

The preceding train window has released-strict reward 0.3271 and
executable-strict success 0.3196, for 97.71% raw executable precision. All 96
released-only rows agree under deterministic re-grading, all canonical
solutions pass, and the issue-code counts are 80 `equation_mismatch` and 75
`solver_equation_mismatch`, with overlap. Logged rollout errors are zero and
saved-row truncation is 0.53%. Mismatch KL stays at most 0.0023; gradient norm
briefly reaches 1.1775 at step 2347, then returns to 0.0463 at step 2350 with
no numerical failure. The step-2350 trainer and orchestrator checkpoints,
eight distributed trainer shards, stable inference weights, 512 training rows,
and all 3,000 evaluation rows are complete.

Step 2375 is a strong checkpoint: preceding train reward reaches 0.4030,
OP11–20 rises to 24.30%, OP15–20 reaches 12.42%, and OP21–25 holds at 1.60%.
OP20 reaches 5.50%, 0.766 points above the matched strict-filter OP20
checkpoint's 4.734%, although the one-rollout RL estimate remains too noisy for
a superiority claim. New executable-strict OP21 index 24 is manually verified
through Saint-Rivage and Montreval totals 13 and 24 to Clairmont answer 102.
New OP23 index 161 coherently derives Bundle Ranch and South Zoo totals 8 and
19 before Jefferson Circus answer 40. Cumulative breadth reaches 30 OP21
prompts and 17 OP23 prompts; it stays at 27 OP20 prompts, 25 OP22 prompts,
seven OP24 prompts, and two OP25 prompts. Across the full evaluation,
502/3,000 trajectories pass released strict and 489/3,000 pass executable
strict, for 97.41% raw executable precision. Evaluation truncation is 0.30%,
with no rollout errors.

The preceding train window has executable-strict success 0.3964, for 98.35%
raw executable precision. All 85 released-only rows agree under deterministic
re-grading, all canonical solutions pass, and the issue-code counts are 61
`equation_mismatch`, 35 `solver_equation_mismatch`, two `undefined_symbol`,
and 13 `unexpected_node`, with overlap. Logged off-policy cancellation errors
average 2.35% because step 2363 transiently reaches 51.0%; no errors survive
into saved rows, whose truncation rate is 0.12%. Mismatch KL stays at most
0.0041 and gradient norm at most 0.5019, ending at 0.0005 and 0.1521. The
step-2375 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 2400 retains 23.75% on OP11–20 and 12.00% on OP15–20 while OP21–25
returns to its 2.80% run high. OP20 reaches a new run high of 7.00%, 2.266
points above the matched strict-filter checkpoint's 4.734%, although a matched
128-rollout RL evaluation is still needed to establish a lower-variance
comparison. New executable-strict OP20 index 46 is manually verified through
Hawkesbury, Brightford, and Glenfield totals 4, 6, and 44 to Westhaven answer
47. New OP21 index 165 coherently derives Cedar Valley total 9 and Maple Creek
answer 63. Cumulative breadth reaches 28 OP20 prompts and 31 OP21 prompts; it
stays at 25 OP22 prompts, 17 OP23 prompts, seven OP24 prompts, and two OP25
prompts. The released-only OP21 index 24 is invalid: it writes `26 + 57 = 59`
and then `59 + 19 = 102`, two compensating arithmetic errors. Across the full
evaluation, 503/3,000 trajectories pass released strict and 493/3,000 pass
executable strict, for 98.01% raw executable precision. Evaluation truncation
is 0.27%, with no rollout errors.

The preceding train window has released-strict reward 0.3396 and
executable-strict success 0.3359, for 98.92% raw executable precision. All 47
released-only rows agree under deterministic re-grading, all canonical
solutions pass, and the issue-code counts are 32 `equation_mismatch`, 21
`solver_equation_mismatch`, three `unexpected_node`, five each of
`definition_dependency_mismatch` and `definition_value_mismatch`, one
`expression_syntax`, and one `undefined_symbol`, with overlap. Logged
off-policy cancellation errors average 1.23% and peak transiently at 24.8% on
step 2380; saved rows have no errors and 0.05% truncation. Mismatch KL stays at
most 0.0036 and gradient norm at most 0.5280, ending at 0.0000 and 0.0167. The
step-2400 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 2425 raises OP11–20 to 25.45% and sets a new OP15–20 high of 13.00%,
while OP21–25 remains strong at 2.50%. OP20 scores 6.50%, 1.766 points above
the matched strict-filter checkpoint's 4.734% but still within the uncertainty
of a one-rollout checkpoint estimate. All executable-strict OP20–23 positives
repeat known prompts, so cumulative breadth stays at 28 OP20 prompts, 31 OP21
prompts, 25 OP22 prompts, 17 OP23 prompts, seven OP24 prompts, and two OP25
prompts. Across the full evaluation, 534/3,000 trajectories pass released
strict and 524/3,000 pass executable strict, for 98.13% raw executable
precision. Evaluation truncation is 0.30%, with no rollout errors.

The preceding train window has released-strict reward 0.3180 and
executable-strict success 0.3073, for 96.61% raw executable precision. All 138
released-only rows agree under deterministic re-grading and all canonical
solutions pass. One OP13 forward-reverse prompt contributes 102/138 rows;
manual samples show the model dropping or duplicating terms to derive false
coefficients such as `17*x + 4` or `19*x + 4` instead of `18*x + 4`, then
forcing answer 4 through invalid solver equations. The issue-code counts are
42 `equation_mismatch`, 122 `solver_equation_mismatch`, and one
`unexpected_node`, with overlap. Logged off-policy cancellation errors average
0.74% and peak transiently at 18.6% on step 2420; saved rows have no errors and
0.12% truncation. Mismatch KL stays at most 0.0014 and gradient norm at most
0.1491, ending at 0.0002 and 0.0702. The step-2425 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2450 keeps OP11–20 high at 25.15% while setting new highs of 13.33% on
OP15–20 and 3.00% on OP21–25. OP20 scores 6.00%, still 1.266 points above the
matched strict-filter checkpoint's 4.734% one-sample expectation. New
executable-strict OP22 index 163 is manually verified through Cedar Valley and
Oakridge Riverside totals 8 and 42 to Maple Creek answer 33, expanding OP22
breadth to 26 prompts. OP24 replicates known index 69; other cumulative breadth
stays at 28 OP20 prompts, 31 OP21 prompts, 17 OP23 prompts, seven OP24 prompts,
and two OP25 prompts. The released-only OP21 index 13 is invalid, writing
`45 + 27 = 60` and then `60 + 36 = 108` to force the gold answer. Across the
full evaluation, 533/3,000 trajectories pass released strict and 518/3,000
pass executable strict, for 97.19% raw executable precision. Evaluation
truncation is 0.30%, with no rollout errors.

The preceding train window has released-strict reward 0.3514 and
executable-strict success 0.3468, for 98.69% raw executable precision. All 59
released-only rows agree under deterministic re-grading, all canonical
solutions pass, and the issue-code counts are 43 `equation_mismatch` and 40
`solver_equation_mismatch`, with overlap. Logged off-policy cancellation
errors average 1.19% and peak transiently at 21.7% on step 2432; saved rows
have no errors and 0.11% truncation. Mismatch KL stays at most 0.0003 and
gradient norm at most 0.3261, ending at 0.0001 and 0.0735. The step-2450
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 2475 has the highest 25-step mean train reward so far, 0.4512, but
validation falls to 22.90% on OP11–20, 11.17% on OP15–20, and 2.10% on
OP21–25. This is another direct demonstration that sampled train reward is not
a monotonic validation proxy. OP20 scores 5.00%, slightly above the matched
strict-filter checkpoint's 4.734%. No new executable-strict OP20–25 prompt
coverage appears, so cumulative breadth stays at 28 OP20 prompts, 31 OP21
prompts, 26 OP22 prompts, 17 OP23 prompts, seven OP24 prompts, and two OP25
prompts. The released-only OP21 index 154 is invalid, writing `15 + 60 = 63`
and then `63 + 36 = 111` to force the gold answer. Across the full evaluation,
479/3,000 trajectories pass released strict and 472/3,000 pass executable
strict, for 98.54% raw executable precision. Evaluation truncation is 0.33%,
with no rollout errors.

The train window has executable-strict success 0.4446, for 98.55% raw
executable precision. All 84 released-only rows agree under deterministic
re-grading, all canonical solutions pass, and the issue-code counts are 81
`equation_mismatch`, 41 `solver_equation_mismatch`, and three
`unexpected_node`, with overlap. Logged off-policy cancellation errors average
0.73% and peak transiently at 18.2% on step 2461; saved rows have no errors and
0.02% truncation. Mismatch KL stays at most 0.0015 and gradient norm at most
0.4002, ending at 0.0002 and 0.0197. The step-2475 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2500 rebounds to 24.95% on OP11–20, 12.83% on OP15–20, and 2.80% on
OP21–25. OP20 scores 5.00%, only 0.266 percentage points above the matched
strict-filter OP20 SFT checkpoint's 4.734% unbiased strict pass@1. The RL
checkpoint uses one rollout on each of 200 prompts, while the SFT estimate
uses 128 rollouts per prompt, so this difference is not evidence that RL is
better. New executable-strict coverage appears at OP21 index 155 and OP23
index 94. Manual inspection confirms coherent chains to answers 61 and 216,
expanding cumulative breadth to 32 OP21 prompts and 18 OP23 prompts; breadth
stays at 28 OP20 prompts, 26 OP22 prompts, seven OP24 prompts, and two OP25
prompts. Released-only OP22 index 10 reuses a rebound variable and writes the
false equality `18 + 5 = 23`; OP24 index 144 writes `2 + 78 = 56` followed by
`56 + 80 = 160`. Across the full evaluation, 527/3,000 trajectories pass
released strict and 512/3,000 pass the raw executable grader. Two of the 15
raw mismatches are correct irrelevant facts from the prompt, so manual
semantic adjustment gives 514 valid trajectories and 97.53% precision among
released passes, versus 97.15% from the unadjusted executable grader.

The preceding train window has released-strict reward 0.2848 and raw
executable-strict success 0.2663, for 93.50% raw executable precision. All 237
released-only rows reproduce under deterministic re-grading and all canonical
solutions pass, but manual cluster inspection identifies 105 executable-grader
false rejects: 103 rows add a correctly computed adult-crow fact stated in
prompt 765 and two add a correct comedy fact stated in prompt 230. Counting
these benign distractors gives 96.38% semantic precision and leaves 132
genuine defects among 3,645 released passes. The other five pure
`unexpected_node` rows, from prompt 156, compute an irrelevant parrot fact
incorrectly. This audit shows that `unexpected_node` should be checked against
the problem text rather than treated as an automatic semantic failure. Logged
off-policy cancellation errors average 1.83% and peak transiently at 24.8%; no
errors survive into saved rows, whose truncation rate is 0.09%. Mismatch KL
briefly reaches 0.0222 and recovers to 0.0001 by step 2500; gradient norm stays
at most 0.4831. The step-2500 trainer and orchestrator checkpoints, eight
distributed trainer shards, stable inference weights, 512 training rows, and
all 3,000 evaluation rows are complete.

Step 2525 raises OP11–20 to 25.60% and sets a new OP21–25 high of 3.10%, while
OP15–20 remains strong at 12.67%. OP20 scores 4.50%, only 0.234 percentage
points below the matched strict-filter OP20 SFT checkpoint's 4.734% unbiased
pass@1 and well within the noise of this checkpoint's single rollout per 200
prompts. OP21, OP22, OP23, OP24, and OP25 score 7.0%, 5.0%, 2.0%, 1.5%, and
0.0%, respectively. New executable-strict coverage appears at OP20 index 41,
OP22 index 70, and OP24 index 144. Manual inspection confirms coherent chains
to answers 83, 148, and 160; notably, the new OP24 trajectory correctly derives
Mayer Aquarium totals after the same prompt produced an invalid released-only
trajectory at step 2500. Cumulative executable breadth reaches 29 OP20 prompts,
32 OP21 prompts, 27 OP22 prompts, 18 OP23 prompts, eight OP24 prompts, and two
OP25 prompts.

Across the full step-2525 evaluation, 543/3,000 trajectories pass released
strict and 528/3,000 pass the raw executable grader, for 97.24% raw executable
precision. Deterministic re-grading agrees on all 15 mismatches and every
canonical solution passes. Two pure `unexpected_node` mismatches, OP12 indices
30 and 102, add correctly computed but irrelevant facts stated in the prompt;
counting those benign extras gives 530 semantically valid trajectories and
97.61% semantic precision among released passes. The remaining 13 mismatches
are genuine errors. For example, OP16 index 50 incorrectly computes Mayer
Aquarium deer as 45 instead of 7. Evaluation has no rollout errors and 5/3,000
truncations.

The preceding train window has released-strict reward 0.4025 and executable
strict success 0.3870, for 96.14% executable precision. All 199 released-only
rows agree under deterministic re-grading, all canonical solutions pass, and
manual inspection confirms that the three pure `unexpected_node` rows are also
substantive: they compute Shoreline private-middle schools from the Oakbridge
total rather than the stated Riverton total. Two forward-reverse prompts
contribute 146/199 mismatches. Prompt 706 drops terms to derive `44*x + 15`
instead of `48*x + 15` and then forces answer 1; prompt 127 writes
`11*x + 1 = 34` but changes this to `11*x = 31` before still claiming answer
3. Issue-code counts are 132 `equation_mismatch`, 182
`solver_equation_mismatch`, two `undefined_symbol`, one `expression_syntax`,
and three `unexpected_node`, with overlap. Logged off-policy cancellation
errors average 1.93% and peak transiently at 31.1% on step 2508; no errors
survive into saved rows, whose truncation rate is 0.13%. Mismatch KL stays at
most 0.0005 and gradient norm at most 0.1438, ending at 0.0000 and 0.0542.
The step-2525 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 2550 eases to 24.85% on OP11–20, 11.58% on OP15–20, and 2.30% on
OP21–25 despite a high preceding train reward of 0.3738, again showing that
sampled train reward is not a monotonic validation proxy. OP20 released strict
is 5.00%, only 0.266 percentage points above the matched strict-filter OP20
checkpoint's 4.734% and still a statistical tie; one of those ten OP20 passes
has an invalid displayed equality, so executable strict is 4.50%. OP21, OP22,
OP23, OP24, and OP25 released strict are 5.0%, 2.0%, 3.5%, 1.0%, and 0.0%.
All executable frontier positives repeat previously solved prompts, leaving
cumulative breadth at 29 OP20 prompts, 32 OP21 prompts, 27 OP22 prompts, 18
OP23 prompts, eight OP24 prompts, and two OP25 prompts.

Across the full evaluation, 520/3,000 trajectories pass released strict and
508/3,000 pass the raw executable grader, for 97.69% raw executable precision.
Deterministic re-grading agrees on all 12 mismatches and every canonical
solution passes. OP12 index 30 again adds correct irrelevant Golden Banana
facts, and OP13 index 54 adds a correctly computed but irrelevant Clairmont
total. Counting these two benign extras gives 510 semantically valid
trajectories and 98.08% semantic precision; the other ten mismatches are
genuine defects. OP20 index 49, for example, writes `12 + 68 = 68` while
retaining the correct final answer 114. Evaluation has no rollout errors and
5/3,000 truncations.

The preceding train window has released-strict reward 0.3738 and executable
strict success 0.3669, for 98.14% executable precision. All 89 released-only
rows agree under deterministic re-grading and all canonical solutions pass.
The two pure `unexpected_node` rows are substantive: their extra Riverton
regional-medical step uses a Shoreline elementary count where the prompt
requires the Ruby Bay elementary count. Issue-code counts are 77
`equation_mismatch`, 66 `solver_equation_mismatch`, and two `unexpected_node`,
with overlap; the largest single prompt contributes 36/89 mismatches. Logged
off-policy cancellation errors average 2.64% and peak transiently at 28.7% on
step 2550; none survive into saved rows, whose truncation rate is 0.10%.
Mismatch KL stays at most 0.0003 and gradient norm at most 0.2013, ending at
0.0000 and 0.0355. The step-2550 trainer and orchestrator checkpoints, eight
distributed trainer shards, stable inference weights, 512 training rows, and
all 3,000 evaluation rows are complete.

Step 2575 rebounds to 25.15% on OP11–20 and sets a new OP15–20 high of
14.08%, with OP21–25 at 2.60%. OP20 reaches 5.50% on both released and
executable strict, 0.766 percentage points above the matched strict-filter
OP20 checkpoint's 4.734%, although the one-rollout checkpoint estimate remains
too noisy for a superiority claim. OP21, OP22, OP23, OP24, and OP25 score
7.0%, 3.0%, 2.0%, 1.0%, and 0.0%. New OP21 index 146 is manually verified as
a coherent Hamilton Farm–Bundle Ranch chain: the two totals are 36 and 76 and
the final answer is 76. Cumulative executable breadth therefore reaches 33
OP21 prompts; it remains at 29 OP20 prompts, 27 OP22 prompts, 18 OP23 prompts,
eight OP24 prompts, and two OP25 prompts.

Across the full evaluation, 529/3,000 trajectories pass released strict and
521/3,000 pass executable strict, for 98.49% executable precision. All eight
mismatches reproduce under deterministic re-grading, every canonical solution
passes, and every mismatch contains a substantive arithmetic, solver, or
undefined-symbol error; there are no benign pure-extra-node false rejects in
this evaluation. Evaluation has no rollout errors and 8/3,000 truncations.

The preceding train window has released-strict reward 0.3427 and raw
executable-strict success 0.3373, for 98.45% raw executable precision.
Deterministic re-grading agrees on all 68 mismatches and all canonical
solutions pass. The two pure `unexpected_node` rows add correctly computed but
irrelevant prompt subgraphs, so counting them gives 4,320 semantically valid
trajectories among 4,386 released passes, or 98.50% semantic precision. The
remaining 66 mismatches are genuine defects. Issue-code counts are 63
`equation_mismatch`, 22 `solver_equation_mismatch`, and two `unexpected_node`,
with overlap; the two largest prompt clusters contribute 46/68 mismatches.
Logged off-policy cancellation errors average 1.54% and peak transiently at
38.6% on step 2567; no errors survive into saved rows, which contain only one
truncation in 12,800 trajectories. Mismatch KL stays at most 0.0008 and
gradient norm at most 0.3432, ending at 0.0005 and 0.2370. The step-2575
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 2600 holds OP11–20 at 25.20% and OP21–25 at 2.60%, while OP15–20 falls
from its step-2575 high to 12.17% despite a higher preceding train reward of
0.3957. OP20 reaches 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 checkpoint's 4.734%,
but still requires a matched 128-rollout evaluation for a lower-variance
comparison. OP21, OP22, OP23, OP24, and OP25 score 6.0%, 3.5%, 3.0%, 0.5%,
and 0.0%. New OP24 index 6 is manually verified as a coherent Northwood–Golden
Banana–Verdi chain with intermediate totals 6 and 21 and final answer 55.
Cumulative executable breadth reaches nine OP24 prompts; it remains at 29
OP20 prompts, 33 OP21 prompts, 27 OP22 prompts, 18 OP23 prompts, and two OP25
prompts.

Across the full evaluation, 530/3,000 trajectories pass released strict and
521/3,000 pass the raw executable grader, for 98.30% raw executable precision.
Deterministic re-grading agrees on all nine mismatches and all canonical
solutions pass. OP12 index 30 and OP13 index 54 again add correct irrelevant
subgraphs; counting these two benign extras gives 523 semantically valid
trajectories and 98.68% semantic precision among released passes. The other
seven mismatches are genuine defects, including the recurring incorrect Mayer
Aquarium deer computation at OP16 index 50. Evaluation has no rollout errors
and 5/3,000 truncations.

The preceding train window has released-strict reward 0.3957 and raw
executable-strict success 0.3863, for 97.63% raw executable precision. All 120
mismatches reproduce under deterministic re-grading and every canonical
solution passes. The sole pure `unexpected_node` row adds a correct irrelevant
Clearwater private-middle-school copy, so semantic adjustment gives 4,946
valid trajectories among 5,065 released passes, or 97.65% precision, leaving
119 genuine defects. Issue-code counts are 100 `equation_mismatch`, 83
`solver_equation_mismatch`, and one `unexpected_node`, with overlap; the
largest prompt cluster contributes 40/120 mismatches. Logged off-policy
cancellation errors average 0.89% and peak transiently at 17.5% on step 2598;
no errors survive into saved rows, whose truncation rate is 0.04%. An isolated
one-trajectory batch at step 2590 raises gradient norm to 2.2394, but the next
step returns to 0.0657 and step 2600 ends at 0.0316. Mismatch KL stays at most
0.0021 and ends at 0.0001. The step-2600 trainer and orchestrator checkpoints,
eight distributed trainer shards, stable inference weights, 512 training rows,
and all 3,000 evaluation rows are complete.

Step 2625 records 24.80% on OP11–20, 12.25% on OP15–20, and 3.10% on
OP21–25. OP20 is 4.50% on both released and executable strict, statistically
tied with the matched strict-filter OP20 checkpoint's 4.734% estimate. OP21,
OP22, OP23, OP24, and OP25 released strict are 5.5%, 5.5%, 2.5%, 1.5%, and
0.5%. The sole OP25 pass, new index 22, also passes executable strict and is
manually verified as a coherent West Sahara–Northwood–Golden Banana chain with
intermediate totals 10 and 35 and final answer 58. Cumulative executable OP25
breadth therefore reaches three prompts; breadth remains at 29 OP20 prompts,
33 OP21 prompts, 27 OP22 prompts, 18 OP23 prompts, and nine OP24 prompts.

Across the full evaluation, 527/3,000 trajectories pass released strict and
513/3,000 pass the raw executable grader, for 97.34% raw executable precision.
Deterministic re-grading agrees on all 14 mismatches and every canonical
solution passes. OP11 index 152 and OP12 index 30 add correctly computed but
irrelevant prompt facts; counting these two benign extras gives 515
semantically valid trajectories and 97.72% semantic precision. The remaining
12 mismatches are genuine, including an incorrect extra Northwood subgraph at
OP11 index 68 and recurring defects at OP14 index 55 and OP16 index 50.
Evaluation has no rollout errors and 5/3,000 truncations.

The preceding train window exposes a substantial verifier-hacking cluster.
Released-strict reward is 0.3035, but executable-strict success is only 0.2781:
3,560 of 3,885 released passes are executable-consistent, or 91.63%. All 325
mismatches reproduce under deterministic re-grading, every canonical solution
passes, and manual inspection confirms that the four pure `unexpected_node`
rows are also substantively wrong. The three largest prompt clusters account
for 214/325 mismatches. Prompt 511 drops an `18*x` term while deriving the Ruby
Bay total and then forces answer 1; prompt 580 correctly derives `22*x + 12`
but changes the solver equation from `22*x = 66` to `22*x = 72` before still
claiming answer 3; prompt 588 changes the Bundle Ranch coefficient from
`15*x + 32` to `17*x + 32` and forces answer 2. Issue-code counts are 260 each
of `equation_mismatch` and `solver_equation_mismatch`, five `unexpected_node`,
and one `expression_syntax`, with overlap.

Logged off-policy cancellation errors average 1.60% and peak transiently at
21.2% on step 2618; they immediately return to zero and none survive into
saved rows, whose truncation rate is 0.04%. Mismatch KL reaches 0.0063 at step
2615 and ends at 0.0001. Gradient norm reaches 1.5925 at step 2602 and ends at
0.1232, with no numerical failure. The step-2625 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2650 improves OP11–20 to 25.70%, with OP15–20 at 12.33% and OP21–25
at 2.70%. OP20 reaches 5.50% on both released and executable strict, 0.766
percentage points above the matched strict-filter OP20 checkpoint's 4.734%
estimate but still within single-rollout checkpoint noise. OP21 released strict
is 6.0%, but one response falsely writes a Taylor total as `x + 120` instead of
`x + 96` and then forces solution 2, so executable strict is 5.5%. OP22 and
OP23 score 5.0% and 2.5%; OP24 and OP25 are zero. No new executable OP20–25
prompt coverage appears, so cumulative breadth stays at 29, 33, 27, 18, nine,
and three prompts, respectively.

Across the full evaluation, 541/3,000 trajectories pass released strict and
523/3,000 pass the raw executable grader, for 96.67% raw executable precision.
Deterministic re-grading agrees on all 18 mismatches and every canonical
solution passes. OP12 index 30 is the sole benign pure-extra-node false reject;
counting it gives 524 semantically valid trajectories and 96.86% semantic
precision. The remaining 17 mismatches are genuine arithmetic or solver
defects. Evaluation has no rollout errors and 6/3,000 truncations.

The preceding train window has released-strict reward 0.3033 and
executable-strict success 0.2965, for 97.76% executable precision. All 87
released-only rows reproduce under deterministic re-grading, every canonical
solution passes, and every mismatch has a substantive equality or solver
error. Issue-code counts are 80 `equation_mismatch` and 64
`solver_equation_mismatch`, with overlap; the largest prompt cluster
contributes 33/87 mismatches. Logged off-policy cancellation errors average
1.34% and peak transiently at 25.3% on step 2636; none survive into saved rows,
whose truncation rate is 0.04%. Mismatch KL stays at most 0.0004 and gradient
norm at most 0.4753, ending at 0.0001 and 0.0174. The step-2650 trainer and
orchestrator checkpoints, eight distributed trainer shards, stable inference
weights, 512 training rows, and all 3,000 evaluation rows are complete.

Step 2675 has a high preceding train reward of 0.4194, but validation falls to
24.20% on OP11–20 and 2.30% on OP21–25; OP15–20 remains strong at 12.75%.
OP20 is 5.00% on both released and executable strict, effectively tied with
the matched strict-filter OP20 checkpoint's 4.734% estimate. OP21 released
strict is 4.5%, but one invalid arithmetic trajectory lowers executable strict
to 4.0%; OP22, OP23, OP24, and OP25 score 4.0%, 2.0%, 1.0%, and 0.0%. No new
executable frontier prompt appears, leaving cumulative OP20–25 breadth at 29,
33, 27, 18, nine, and three prompts.

Across the full evaluation, 507/3,000 trajectories pass released strict and
495/3,000 pass the raw executable grader, for 97.63% raw executable precision.
Deterministic re-grading agrees on all 12 mismatches and every canonical
solution passes. OP13 index 54 adds a correct irrelevant Clairmont total;
counting that benign extra gives 496 semantically valid trajectories and
97.83% semantic precision. The remaining 11 mismatches are genuine defects.
Evaluation has no rollout errors and only two truncations.

The preceding train window has executable-strict success 0.4085, for 97.41%
precision among 5,368 released-strict passes. All 139 mismatches reproduce
under deterministic re-grading and all canonical solutions pass. The 75 pure
`unexpected_node` rows are not grader false rejects: 45 rows compute a
Clearwater medical-school distractor from the wrong Shoreline dependency, and
30 compute a Cedar Valley crow distractor using Beverly Forest owl rather than
the stated Maple Creek eagle. The remaining 64 rows contain displayed
arithmetic or solver errors. Issue-code counts are 61 `equation_mismatch`, 40
`solver_equation_mismatch`, 75 `unexpected_node`, and one `undefined_symbol`,
with overlap.

Logged off-policy cancellation errors average 2.46% and peak transiently at
31.5% on step 2669; none survive into saved rows, whose truncation rate is
0.05%. Mismatch KL stays at most 0.0011 and gradient norm at most 0.2554,
ending at 0.0002 and 0.0613. The step-2675 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2700 sets a new OP11–20 high of 26.25%, with OP15–20 at 12.67% and
OP21–25 at 2.80%. OP20 reaches 6.50% on both released and executable strict,
1.766 percentage points above the matched strict-filter OP20 checkpoint's
4.734% estimate, although a matched 128-rollout comparison is still needed.
OP21, OP22, and OP23 score 5.5%, 6.0%, and 2.5%; OP24 and OP25 are zero. New
executable-strict OP21 index 72 is manually verified through Hawkesbury and
Westhaven totals 6 and 11 to Glenfield answer 12. New OP23 index 80 coherently
derives Ruby, Oakbridge, and Riverton totals 22, 22, and 26 before Shoreline
answer 63. Cumulative executable breadth reaches 34 OP21 prompts and 19 OP23
prompts; it stays at 29 OP20 prompts, 27 OP22 prompts, nine OP24 prompts, and
three OP25 prompts.

Across the full evaluation, 553/3,000 trajectories pass released strict and
548/3,000 pass executable strict, for 99.10% executable precision. All five
mismatches reproduce under deterministic re-grading, every canonical solution
passes, and every mismatch contains a substantive arithmetic or solver error;
there are no extra-node-only disagreements. Evaluation has no rollout errors
and 11/3,000 truncations.

The preceding train window has released-strict reward 0.3859 and
executable-strict success 0.3820, for 98.99% executable precision. All 50
released-only rows agree under deterministic re-grading and all canonical
solutions pass. Issue-code counts are 46 `equation_mismatch`, 29
`solver_equation_mismatch`, one `undefined_symbol`, and one `unexpected_node`,
with overlap; the largest prompt cluster contributes only 9/50 rows. Logged
off-policy cancellation errors average 1.99% and peak transiently at 31.6% on
step 2700; none survive into saved rows, which contain two truncations in
12,800 trajectories. Mismatch KL stays at most 0.0006 and gradient norm at most
0.2468, ending at 0.0004 and 0.2232. The step-2700 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2725 falls to 23.60% on OP11–20 while OP15–20 remains strong at 13.25%
and OP21–25 is 2.30%. OP20 reaches 7.00% on both released and executable
strict, tying the run high and exceeding the matched strict-filter OP20
checkpoint's 4.734% estimate by 2.266 percentage points; a matched 128-rollout
evaluation remains necessary. OP21, OP22, OP23, OP24, and OP25 score 5.0%,
3.5%, 2.5%, 0.5%, and 0.0%. New executable-strict OP23 index 15 is manually
verified through Northwood and West Sahara totals 18 and 80 to Taylor answer
88. Cumulative OP23 breadth reaches 20 prompts; other cumulative OP20–25
breadth remains 29, 34, 27, nine, and three prompts.

Across the full evaluation, 495/3,000 trajectories pass released strict and
483/3,000 pass executable strict, for 97.58% executable precision. All 12
mismatches reproduce under deterministic re-grading, every canonical solution
passes, and each mismatch is substantive; the only pure-extra-node row is the
recurring incorrect Mayer Aquarium deer computation at OP16 index 50.
Evaluation has no rollout errors and 12/3,000 truncations.

The preceding train window has released-strict reward 0.3847 and raw
executable-strict success 0.3687, for only 95.84% raw executable precision.
Manual cluster inspection shows that 164/205 raw mismatches are executable
grader false rejects: they add correctly computed but irrelevant prompt
subgraphs. These comprise 94 rows on prompt 154, 63 on prompt 698, six on
prompt 86, and one on prompt 163. Counting them gives 4,883 semantically valid
trajectories among 4,924 released passes, or 99.17% semantic precision, leaving
41 genuine defects. The issue-code counts are 35 `equation_mismatch`, 30
`solver_equation_mismatch`, and 164 `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.70% and peak transiently at
17.5% on step 2720; no errors survive into saved rows, whose truncation rate is
0.24%. Mismatch KL stays at most 0.0011 and gradient norm at most 0.4958,
ending at 0.0004 and 0.3201. The step-2725 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2750 falls further to 23.15% on OP11–20 and 12.00% on OP15–20, while
OP21–25 is 2.50%. OP20 scores 5.50% on both released and executable strict.
New executable-strict OP20 index 78 is manually verified through Westhaven and
Hawkesbury totals 16 and 52 to answer 52, raising cumulative OP20 breadth to 30
prompts. OP21, OP22, OP23, OP24, and OP25 score 6.5%, 4.5%, 1.0%, 0.0%, and
0.5%; all their executable positives repeat previously solved prompts. Other
cumulative frontier breadth remains 34 OP21 prompts, 27 OP22 prompts, 20 OP23
prompts, nine OP24 prompts, and three OP25 prompts.

Across the full evaluation, 488/3,000 trajectories pass released strict and
472/3,000 pass the raw executable grader, for 96.72% raw executable precision.
Deterministic re-grading agrees on all 16 mismatches and all canonical
solutions pass. OP12 index 30 is a benign extra-node false reject; counting it
gives 473 semantically valid trajectories and 96.93% semantic precision. The
remaining 15 mismatches are genuine defects. Evaluation has no rollout errors
and 7/3,000 truncations.

The preceding train window has released-strict reward 0.3696 and raw
executable-strict success 0.3498, for 94.63% raw executable precision. Of 254
raw mismatches, six pure `unexpected_node` rows add correct irrelevant
subgraphs and one duplicates a Hamilton owl to construct an invalid total.
Semantic adjustment therefore gives 4,483 valid trajectories among 4,731
released passes, or 94.76% precision, leaving 248 genuine defects. The three
largest prompt clusters account for 158/254 mismatches: prompt 215 flips the
sign of `2 - 4` while forcing answer 32, prompt 572 derives `23*x + 4` instead
of `19*x + 4`, and prompt 1126 derives `23*x + 8` instead of `25*x + 8`.
Issue-code counts are 240 `equation_mismatch`, 117
`solver_equation_mismatch`, and seven `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.72% and peak transiently at
19.1% on step 2738; none survive into saved rows, whose truncation rate is
0.05%. Mismatch KL stays at most 0.0026 and gradient norm at most 0.3975,
ending at 0.0001 and 0.1819. The step-2750 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2775 rebounds to 24.20% on OP11–20 and 12.50% on OP15–20, while
OP21–25 falls to 1.90%. OP20 scores 6.00% on both released and executable
strict. OP21, OP22, OP23, OP24, and OP25 score 5.0%, 2.0%, 2.0%, 0.5%, and
0.0%. No new executable OP20–25 prompt coverage appears, so cumulative breadth
stays at 30, 34, 27, 20, nine, and three prompts, respectively.

Across the full evaluation, 503/3,000 trajectories pass released strict and
486/3,000 pass the raw executable grader, for 96.62% raw executable precision.
Deterministic re-grading agrees on all 17 mismatches and every canonical
solution passes. Three pure-extra-node rows—OP11 index 152, OP12 index 30, and
OP13 index 54—add correct irrelevant prompt facts. Counting them gives 489
semantically valid trajectories and 97.22% semantic precision. The remaining
14 mismatches are genuine defects. Evaluation has no rollout errors and
4/3,000 truncations.

The preceding train window has released-strict reward 0.3891 and
executable-strict success 0.3755, for 96.49% executable precision. All 175
released-only rows reproduce under deterministic re-grading and every
canonical solution passes. The nine pure `unexpected_node` rows are
substantive: they assign Evervale's culinarian count from Brightford's total
rather than the stated Westhaven total. Prompt 62 alone contributes 102/175
mismatches by deriving the Valmont total as `20 - 2*x` instead of `20 - x`
and then forcing answer 3. Issue-code counts are 160 `equation_mismatch`, 147
`solver_equation_mismatch`, ten `unexpected_node`, two `expression_syntax`,
and one `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 3.10% and peak transiently at
31.4% on step 2775; none survive into saved rows, whose truncation rate is
0.06%. Mismatch KL stays at most 0.0014 and gradient norm at most 0.5762,
ending at 0.0006 and 0.1200. The step-2775 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2800 remains weak on the trained range at 23.35% on OP11–20 and 11.08%
on OP15–20, while OP21–25 rises to 2.70%. OP20 scores 4.50% on both released
and executable strict. OP21 released strict is 5.5% and executable strict is
5.0%; OP22 reaches 4.5%, OP23 released/executable strict is 3.0%/2.5%, OP24 is
0.5%, and OP25 is zero. New executable-strict OP22 index 4 is manually verified
through Verdi and West Sahara totals 8 and 32 to Taylor answer 40. Cumulative
OP22 breadth reaches 28 prompts; other OP20–25 breadth remains 30, 34, 20,
nine, and three prompts.

Across the full evaluation, 494/3,000 trajectories pass released strict and
484/3,000 pass executable strict, for 97.98% executable precision. All ten
mismatches reproduce under deterministic re-grading, every canonical solution
passes, and each mismatch is substantive; there are no pure-extra-node
disagreements. Evaluation has no rollout errors and 5/3,000 truncations.

The preceding train window has released-strict reward 0.3488 and
executable-strict success 0.3265, for 93.59% executable precision. All 286
released-only rows reproduce under deterministic re-grading and all canonical
solutions pass. The four pure `unexpected_node` rows are also substantively
wrong. Three solver-hacking clusters contribute 221/286 mismatches: prompt 704
derives `6*x + 13` instead of `7*x + 13`, prompt 1168 derives `19*x + 14`
instead of `20*x + 14`, and prompt 515 duplicates a Ruby category to derive
`40*x` instead of `38*x`; all then force the gold answer. Issue-code counts
are 263 `solver_equation_mismatch`, 77 `equation_mismatch`, and four
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.90% and peak transiently at
16.7% on step 2795; none survive into saved rows, whose truncation rate is
0.04%. Mismatch KL stays at most 0.0016 and gradient norm at most 0.4962,
ending at 0.0002 and 0.0777. The step-2800 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2825 rebounds to 25.80% on OP11–20, 12.92% on OP15–20, and 3.00% on
OP21–25. OP20 released strict is 6.50%, while executable strict is 6.00%
because one response contains an invalid displayed equation. The clean 6.00%
estimate is 1.266 percentage points above the matched strict-filter OP20 SFT
checkpoint's 4.734% unbiased strict pass@1, but the RL checkpoint has only one
rollout on each of 200 prompts, so a matched 128-rollout evaluation is needed
to determine whether the improvement is real. OP21, OP22, OP23, OP24, and
OP25 released strict are 5.5%, 6.0%, 3.0%, 0.0%, and 0.5%. The new OP25
index 76 executable pass is manually verified as a coherent Shoreline–Riverton
City–Ruby Bay–Clearwater Bay chain ending at answer 34. Cumulative executable
OP20–25 breadth is therefore 30, 34, 28, 20, nine, and four prompts.

Across the full evaluation, 546/3,000 trajectories pass released strict and
536/3,000 pass the raw executable grader, for 98.17% raw executable precision.
One pure-extra-node disagreement, OP13 index 54, is a correctly computed but
irrelevant Clairmont total; counting it gives 537 semantically valid
trajectories and 98.35% semantic precision. The remaining nine disagreements
are genuine defects. Evaluation has no rollout errors and four truncations.

The preceding train window has released-strict reward 0.4226 and executable-
strict success 0.4136, for 97.87% executable precision. All 115 mismatches
reproduce under deterministic re-grading, all canonical solutions pass, and
manual inspection confirms all four pure `unexpected_node` rows are
substantive errors. Issue-code counts are 100 `equation_mismatch`, 51
`solver_equation_mismatch`, four `unexpected_node`, and one
`undefined_symbol`, with overlap. Logged off-policy cancellation errors
average 0.74% and peak transiently at 18.4%; none survive into saved rows,
whose truncation rate is 0.26%. Mismatch KL stays at most 0.0037 and gradient
norm at most 0.3645, ending at 0.0000 and 0.0469. The step-2825 trainer and
orchestrator checkpoints, eight distributed trainer shards, stable inference
weights, 512 training rows, and all 3,000 evaluation rows are complete.

Step 2850 records 25.05% on OP11–20, 12.58% on OP15–20, and 2.70% on
OP21–25. OP20 reaches 6.50% on both released and executable strict, 1.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% unbiased pass@1, although this remains a noisy one-rollout estimate on
200 prompts. OP21, OP22, OP23, OP24, and OP25 released strict are 4.5%, 4.5%,
4.0%, 0.5%, and 0.0%. New executable-strict OP23 index 86 is manually
verified as a coherent Ruby Bay–Shoreline City–Clearwater Bay chain with
intermediate totals 11 and 25 and final answer 48. Cumulative executable
OP20–25 breadth is therefore 30, 34, 28, 21, nine, and four prompts.

Across the full evaluation, 528/3,000 trajectories pass released strict and
520/3,000 pass the raw executable grader, for 98.48% raw executable precision.
Deterministic re-grading agrees on all eight mismatches, and all 5,000 unique
train and validation canonical solutions pass. OP13 index 54 adds a correctly
computed but irrelevant Clairmont total; counting it gives 521 semantically
valid trajectories and 98.67% semantic precision. The other seven mismatches
are genuine. In particular, OP11 index 68 uses the West Sahara total where the
prompt requires the equal-valued Verdi thriller in an irrelevant Taylor
subgraph, and OP16 index 50 computes Mayer Aquarium deer as 44 rather than 7.
Evaluation has no rollout errors and three truncations. The asynchronous
logger reports policy versions 2849 and 2850 across the scheduled step-2850
shards, so this checkpoint remains an approximate one-step policy mixture.

The preceding train window has released-strict reward 0.3873 and executable-
strict success 0.3773. Raw executable precision is 4,830/4,958, or 97.42%.
One pure-extra-node row adds correctly computed, irrelevant Pine Ridge prompt
facts; counting it gives 4,831 semantically valid trajectories and 97.44%
semantic precision, leaving 127 genuine defects. A single OP13 prompt accounts
for 111/128 raw mismatches across steps 2845–2846: the model corrupts the
correct Bundle Ranch affine total `23*x + 48` into inconsistent variants and
then forces answer 3. Three other pure-extra-node rows are also invalid,
computing Clearwater culinarian as 30 instead of the prompt-consistent 42.
Issue-code counts are 111 `equation_mismatch`, 118
`solver_equation_mismatch`, and four `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.70% and peak transiently at
17.6% on step 2835; none survive into saved rows, whose truncation rate is
0.17%. Mismatch KL stays at most 0.0007 and gradient norm at most 0.5701,
ending at 0.0000 and 0.0529. The step-2850 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2875 records 25.40% on OP11–20, 12.58% on OP15–20, and 2.10% on
OP21–25. OP20 released strict reaches 7.00%, while executable strict is 6.50%
because one response contains inconsistent displayed equations. The clean
estimate is 1.766 percentage points above the matched strict-filter OP20 SFT
checkpoint's 4.734% pass@1, but still has the uncertainty of one rollout on
each of 200 prompts. New executable-strict OP20 index 65 is manually verified
as a coherent Riverton City–Clearwater Bay–Ruby Bay–Shoreline City chain ending
at answer 41. Cumulative executable OP20–25 breadth reaches 31, 34, 28, 21,
nine, and four prompts. OP21, OP22, OP23, OP24, and OP25 released strict are
6.0%, 3.0%, 1.5%, 0.0%, and 0.0%.

Across the full evaluation, 529/3,000 trajectories pass released strict and
521/3,000 pass executable strict, for 98.49% executable precision. All eight
mismatches reproduce under deterministic re-grading and are genuine; there
are no benign extra-node false rejects. The pure-extra-node rows are the
recurring OP14 index 55, which substitutes the Ruby Bay total for the required
Shoreline total, and OP16 index 50, which computes Mayer Aquarium deer as 45
instead of 7. Evaluation has no rollout errors and five truncations. As at
step 2850, the asynchronous logger reports a one-step policy mixture, here
versions 2874 and 2875.

The preceding train window has released-strict reward 0.3513 and executable-
strict success 0.3451, for 98.22% raw executable precision among 4,497
released passes. Manual inspection finds that all 18 pure-extra-node rows are
benign: 11 correctly derive the irrelevant Rêves de Belleville total as
`4*x`, and seven correctly derive Hawkesbury public highschool as 36. Counting
them gives 4,435 semantically valid trajectories and 98.62% semantic
precision, leaving 62 genuine defects. Issue-code counts are 54
`equation_mismatch`, 49 `solver_equation_mismatch`, one `undefined_symbol`,
and 18 `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 2.17% and peak transiently at
22.3% on step 2874; none survive into saved rows, whose truncation rate is
0.12%. Mismatch KL stays at most 0.0011 and gradient norm at most 0.3171,
ending at 0.0001 and 0.0393. The step-2875 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 2900 sets a new OP11–20 run high of 26.40%, with OP15–20 at 13.67% and
OP21–25 at 2.80%. OP20 released strict is 7.00%, while one invalid displayed
equality lowers executable strict to 6.50%. The clean score remains 1.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1, but is still a noisy one-rollout estimate on 200 prompts.
OP21, OP22, OP23, OP24, and OP25 released strict are 7.0%, 3.5%, 3.0%, 0.0%,
and 0.5%. The OP25 pass repeats previously verified index 22; no new
executable OP20–25 prompt appears, so cumulative breadth remains 31, 34, 28,
21, nine, and four prompts.

Across the full evaluation, 556/3,000 trajectories pass released strict and
547/3,000 pass executable strict, for 98.38% executable precision. All nine
mismatches reproduce under deterministic re-grading and are genuine. Six
contain inconsistent arithmetic equalities, five contain invalid solver
equalities, and the sole pure-extra-node row is the recurring OP16 index 50,
which computes Mayer Aquarium deer from the wrong dependency. Evaluation has
no rollout errors and six truncations. The scheduled evaluation again mixes
the adjacent asynchronous policy versions 2899 and 2900.

The preceding train window has released-strict reward 0.3774 and executable-
strict success 0.3645. All 165 released-only rows are genuinely defective, so
raw and semantic executable precision are both 4,666/4,831, or 96.58%. One
OP12 prompt contributes 87/165 mismatches: the model correctly obtains an
intermediate difference of `-3`, then silently changes `2 + (-3)` into
`2 + 3 = 5` to retain the gold answer. The two pure-extra-node rows are also
invalid, deriving Clearwater public highschool as `4 + x` where the prompt
requires the fixed Shoreline elementary count. Issue-code counts are 144
`equation_mismatch`, 50 `solver_equation_mismatch`, two `unexpected_node`,
and one each of `definition_dependency_mismatch` and
`definition_value_mismatch`, with overlap.

Logged off-policy cancellation errors average 1.43% and peak transiently at
18.0% on step 2894; none survive into saved rows, which contain one truncation
in 12,800 trajectories. Mismatch KL stays at most 0.0006 and gradient norm at
most 0.1800, ending at 0.0001 and 0.1198. The step-2900 trainer and
orchestrator checkpoints, eight distributed trainer shards, stable inference
weights, 512 training rows, and all 3,000 evaluation rows are complete.

Step 2925 raises the OP11–20 run high to 26.60%, with OP15–20 at 13.17% and
OP21–25 at 2.70%. OP20 reaches 7.00% on both released and executable strict,
tying the clean run high and exceeding the matched strict-filter OP20 SFT
checkpoint's 4.734% pass@1 by 2.266 percentage points. The estimate still has
only one rollout on each of 200 prompts. OP21, OP22, OP23, OP24, and OP25
released strict are 5.5%, 4.0%, 3.0%, 0.5%, and 0.5%. OP24 index 13 and OP25
index 22 are previously verified prompts; no new executable frontier prompt
appears, so cumulative OP20–25 breadth remains 31, 34, 28, 21, nine, and four.

Across the full evaluation, 559/3,000 trajectories pass released strict and
546/3,000 pass executable strict, for 97.67% executable precision. All 13
mismatches reproduce under deterministic re-grading and are genuine. The two
pure-extra-node cases invent a nonexistent Riverton culinarian subgraph at
OP13 index 32 and incorrectly compute Mayer Aquarium deer at OP16 index 50.
The remaining rows contain eight inconsistent arithmetic equalities, six
invalid solver equalities, and one undefined symbol, with overlap. Evaluation
has no rollout errors and four truncations. The scheduled evaluation again
mixes adjacent asynchronous policy versions, here 2924 and 2925.

The preceding train window has released-strict reward 0.3804 and executable-
strict success 0.3720, for 97.78% raw executable precision among 4,869
released passes. Six of ten pure-extra-node rows correctly derive irrelevant
Saint-Rivage and Rêves de Belleville facts. Counting them gives 4,767
semantically valid trajectories and 97.91% semantic precision, leaving 102
genuine defects. The other four extra-node rows use wrong dependencies or
invent an unstated category. Two solver-hacking clusters contribute 66/102
genuine defects: one corrupts the Mayer Aquarium affine total while forcing
answer 2, and the other changes the South Zoo total from `19*x + 4` to
`22*x + 4` while forcing answer 4. Issue-code counts are 95
`equation_mismatch`, 84 `solver_equation_mismatch`, and ten
`unexpected_node`, with overlap.

There are no logged off-policy cancellation errors in this 25-step window and
no errors in saved rows. Saved-row truncation is 0.06%. Mismatch KL stays at
most 0.0004 and gradient norm at most 0.2890, ending at 0.0002 and 0.2890.
The step-2925 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 2950 records 26.05% on OP11–20, 13.75% on OP15–20, and 2.90% on
OP21–25. OP20 reaches 6.50% on both released and executable strict, 1.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but still within the uncertainty of this one-rollout checkpoint
estimate. OP21, OP22, OP23, OP24, and OP25 score 5.0%, 5.0%, 3.5%, 0.5%, and
0.5%. New executable-strict OP23 index 95 is manually verified through
Shoreline City and Ruby Bay totals 10 and 30 to Clearwater Bay answer 80,
raising cumulative OP23 breadth to 22 prompts. Other cumulative OP20–25
breadth remains 31, 34, 28, nine, and four prompts.

Across the full evaluation, 550/3,000 trajectories pass released strict and
541/3,000 pass the raw executable grader, for 98.36% raw executable precision.
OP13 index 54 adds a correctly computed but irrelevant Clairmont total;
counting it gives 542 semantically valid trajectories and 98.55% semantic
precision. The other eight mismatches are genuine, including the recurring
incorrect Mayer Aquarium deer subgraph at OP16 index 50. Evaluation has no
rollout errors and five truncations. The scheduled evaluation again mixes
adjacent asynchronous policy versions 2949 and 2950.

The preceding train window has released-strict reward 0.3691 and executable-
strict success 0.3559. Raw executable precision is 4,555/4,724, or 96.42%,
but 124/125 pure-extra-node mismatches come from one known grader-false-reject
cluster: every row correctly derives the irrelevant prompt fact that Mayer
Aquarium adult crow equals Bundle Ranch adult blue jay, both 20. Counting
these rows gives 4,679 semantically valid trajectories and 99.05% semantic
precision, leaving 45 genuine defects. The remaining extra-node row computes
one Riverton regional-medical distractor from the wrong dependency. Issue-code
counts are 40 `equation_mismatch`, nine `solver_equation_mismatch`, and 125
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 2.36% and peak transiently at
23.9% on step 2946; none survive into saved rows, which have no truncations.
Mismatch KL stays at most 0.0008 and gradient norm at most 0.3051, ending at
0.0001 and 0.3051. The step-2950 trainer and orchestrator checkpoints, eight
distributed trainer shards, stable inference weights, 512 training rows, and
all 3,000 evaluation rows are complete.

Step 2975 has a high preceding train reward of 0.4312, while validation eases
to 25.85% on OP11–20, 12.75% on OP15–20, and 2.80% on OP21–25. This is another
example of sampled train reward not being a monotonic held-out proxy. OP20
scores 5.50% on both released and executable strict, 0.766 percentage points
above the matched strict-filter OP20 SFT checkpoint's 4.734% pass@1 but within
single-rollout uncertainty. OP21, OP22, OP23, OP24, and OP25 score 6.0%, 5.0%,
1.5%, 0.5%, and 1.0%.

New executable-strict OP25 index 18 is manually verified through Golden Banana
and West Sahara totals 5 and 24 to Verdi answer 108, raising cumulative OP25
breadth to five prompts. Other cumulative OP20–24 breadth remains 31, 34, 28,
22, and nine prompts. Across the full evaluation, 545/3,000 trajectories pass
released strict and 535/3,000 pass the raw executable grader, for 98.17% raw
executable precision. OP12 index 30 adds a correctly computed but irrelevant
prompt fact; counting it gives 536 semantically valid trajectories and 98.35%
semantic precision. The other nine mismatches are genuine. Evaluation has no
rollout errors and four truncations, and again mixes adjacent asynchronous
policy versions 2974 and 2975.

The train window has executable-strict success 0.4285, for 99.38% executable
precision among 5,519 released passes. All 34 mismatches are genuine. The four
pure-extra-node rows either construct an incorrect Pine Ridge total or derive
Shoreline private-middle schools from the Oakbridge total instead of the
required Riverton total. Issue-code counts are 24 `equation_mismatch`, 11
`solver_equation_mismatch`, and four `unexpected_node`, with overlap; the
largest single prompt cluster contains only eight rows.

Logged off-policy cancellation errors average 1.40% and peak transiently at
17.9% on step 2973; none survive into saved rows, whose truncation rate is
0.05%. Mismatch KL stays at most 0.0005 and gradient norm at most 0.1584,
ending at 0.0001 and 0.0275. The step-2975 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3000 records a preceding train reward of 0.3993, with validation at
25.05% on OP11–20, 12.17% on OP15–20, and 2.80% on OP21–25. OP20 scores 4.50%
on both released and executable strict, 0.234 percentage points below the
matched strict-filter OP20 SFT checkpoint's 4.734% pass@1 and statistically
tied. OP21, OP22, OP23, OP24, and OP25 score 4.5%, 6.0%, 2.5%, 0.5%, and
0.5%.

New executable-strict OP24 index 15 is manually verified through Rêves de
Belleville and Valmont totals 8 and 20 to Clairmont answer 41, raising
cumulative OP24 breadth to ten prompts. Other cumulative OP20–25 breadth
remains 31, 34, 28, 22, and five prompts. Across the full evaluation,
529/3,000 trajectories pass released strict and 517/3,000 pass the raw
executable grader, for 97.73% raw executable precision. OP12 index 30 adds a
correctly computed but irrelevant prompt fact; counting it gives 518
semantically valid trajectories and 97.92% semantic precision. The other 11
mismatches are genuine. Evaluation has no rollout errors and two truncations,
and again mixes adjacent asynchronous policy versions 2999 and 3000.

The train window has executable-strict success 0.3937, for 98.59% executable
precision among 5,111 released passes. All 72 mismatches are genuine and no
extra-node ambiguity appears. Two prompt clusters contribute 35/72 defects:
one corrupts a Jefferson Circus affine total and forces answer 2, while the
other writes false equalities such as `50 + 36 = 74` before retaining answer
90. Issue-code counts are 70 `equation_mismatch`, 35
`solver_equation_mismatch`, and one `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.22% and peak transiently at
30.6% on step 2990; none survive into saved rows, whose truncation rate is
0.02%. Mismatch KL stays at most 0.0005 and gradient norm at most 0.5232,
ending at 0.0001 and 0.0838. The step-3000 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3025 rebounds to 25.40% on OP11–20 and 12.67% on OP15–20, while
OP21–25 is 2.40%. OP20 scores 6.50% on both released and executable strict,
1.766 percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. This is still a noisy one-rollout estimate on 200 prompts;
the matched SFT estimate uses 128 rollouts per prompt. OP21, OP22, OP23,
OP24, and OP25 score 5.5%, 3.5%, 2.0%, 1.0%, and 0.0%, respectively. No new
executable OP20–25 prompt appears, so cumulative breadth remains 31, 34, 28,
22, ten, and five prompts.

Across the full evaluation, 532/3,000 trajectories pass released strict and
523/3,000 pass the raw executable grader, for 98.31% raw executable
precision. OP12 index 30 computes a correct but irrelevant prompt fact;
counting it gives 524 semantically valid trajectories and 98.50% semantic
precision. The other eight mismatches are genuine. Issue-code counts are
three `equation_mismatch`, six `solver_equation_mismatch`, and three
`unexpected_node`, with overlap. Evaluation has no rollout errors, five
truncations, and mixes adjacent asynchronous policy versions 3024 and 3025.

The preceding train window has released-strict reward 0.4184 and
executable-strict success 0.4099. The raw executable precision is 97.96%
among 5,356 released passes. Three pure `unexpected_node` rows are grader
false rejects: two correctly compute the prompt-stated Brightford
private-middle-school count, and one correctly computes the prompt-stated
Evervale private-middle-school expression. Counting them gives 5,250
semantically valid passes, 98.02% semantic precision, and 106 genuine
defects. Issue-code counts are 104 `equation_mismatch`, 92
`solver_equation_mismatch`, one `undefined_symbol`, and three
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.50% and peak transiently at
21.6% on step 3025; none survive into saved rows, whose truncation rate is
0.22%. Mismatch KL stays at most 0.0003 and gradient norm at most 0.2888,
ending at 0.0001 and 0.0510. The step-3025 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3050 holds OP11–20 at 25.20% and OP15–20 at 12.33%, while OP21–25
returns to 3.00%, near its 3.10% run high. OP20 scores 5.50% on both released
and executable strict, 0.766 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1 but still within one-rollout checkpoint
noise. OP21, OP22, OP23, OP24, and OP25 score 6.0%, 4.5%, 3.5%, 1.0%, and
0.0%, respectively. No new executable OP20–25 prompt appears, so cumulative
breadth remains 31, 34, 28, 22, ten, and five prompts.

Across the full evaluation, 534/3,000 trajectories pass released strict and
524/3,000 pass the raw executable grader, for 98.13% raw executable
precision. OP12 index 30 is the recurring benign extra prompt fact. OP16
index 50 instead derives Mayer Aquarium deer from the unrelated South Zoo
bear count and is genuinely invalid. Counting only the benign row gives 525
semantically valid trajectories, 98.31% semantic precision, and nine genuine
defects. Issue-code counts are two `equation_mismatch`, seven
`solver_equation_mismatch`, two `unexpected_node`, two `undefined_symbol`,
and one `expression_syntax`, with overlap. Evaluation has no rollout errors,
four truncations, and mixes adjacent asynchronous policy versions 3049 and
3050.

The preceding train window has released-strict reward 0.4408 and
executable-strict success 0.4261. The raw executable precision is 96.67%
among 5,642 released passes. One of four pure `unexpected_node` rows is a
grader false reject that correctly computes a prompt-stated but irrelevant
Hamilton Farm blue-jay count. The other three invent an unstated Maple Creek
eagle node, so counting only the benign row gives 5,455 semantically valid
passes, 96.69% semantic precision, and 187 genuine defects. One prompt alone
contributes 117/188 raw mismatches by changing `23*x + 48` to
`32*x + 48` and then forcing the correct answer. Issue-code counts are 148
`equation_mismatch`, 162 `solver_equation_mismatch`, four
`unexpected_node`, and four `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.84% and peak transiently at
18.1% on step 3043; none survive into saved rows, whose truncation rate is
0.09%. Mismatch KL stays at most 0.0006 and gradient norm at most 0.2950,
ending at 0.0000 and 0.0244. The step-3050 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3075 improves to 25.75% on OP11–20 and 13.00% on OP15–20, while
OP21–25 is 2.70%. OP20 reaches new released and executable run highs of 8.50%
and 8.00%, respectively. The released estimate is 3.766 percentage points
above the matched strict-filter OP20 SFT checkpoint's 4.734% pass@1, but the
RL checkpoint still has only one rollout per prompt. The sole released-only
OP20 response writes `12 + 68 = 68` and then `68 + 34 = 114`, forcing the
correct answer despite both false sums.

OP21, OP22, OP23, OP24, and OP25 score 6.0%, 4.5%, 2.0%, 1.0%, and 0.0%,
respectively. New executable-strict OP22 index 140 is manually verified: it
derives Maple Creek total 7, Cedar Valley total 53, and Pine Ridge total 59.
Cumulative executable OP22 breadth therefore rises to 29 prompts; other
OP20, OP21, OP23, OP24, and OP25 breadth remains 31, 34, 22, ten, and five
prompts. Across the full evaluation, 542/3,000 trajectories pass released
strict and 527/3,000 pass executable strict, for 97.23% executable precision.
Manual inspection
confirms that all 15 mismatches are genuine. Issue-code counts are six
`equation_mismatch`, ten `solver_equation_mismatch`, two `undefined_symbol`,
and two `unexpected_node`, with overlap. Evaluation has no rollout errors,
three truncations, and mixes adjacent asynchronous policy versions 3074 and
3075.

The preceding train window has released-strict reward 0.3837 and
executable-strict success 0.3752, for 97.78% executable precision among 4,911
released passes. Manual inspection confirms that all four pure
`unexpected_node` rows are genuine defects, so all 109 mismatches are
substantive. One prompt contributes 52/109 defects by changing
`15*x + 32` to `21*x + 32` and then forcing the correct solution. Issue-code
counts are 102 `equation_mismatch`, 92 `solver_equation_mismatch`, and four
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 2.85% and peak transiently at
31.4% on step 3057; none survive into saved rows, whose truncation rate is
0.04%. Mismatch KL stays at most 0.0002 and gradient norm at most 0.4530,
ending at 0.0001 and 0.0461. The step-3075 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3100 rises to 26.50% on OP11–20, near the 26.60% run high, while
OP15–20 is 12.83%. OP21–25 sets a new run high of 3.40%. OP20 scores 6.50%
on both released and executable strict, 1.766 percentage points above the
matched strict-filter OP20 SFT checkpoint's 4.734% pass@1 but within the
uncertainty of a one-rollout checkpoint estimate. OP21, OP22, OP23, OP24,
and OP25 score 7.0%, 6.0%, 3.5%, 0.5%, and 0.0%, respectively.

New executable-strict OP22 index 136 is manually verified through Maple
Creek total 21 and Pine Ridge total 49 to Beverly Forest answer 58, raising
cumulative OP22 breadth to 30 prompts. Other cumulative OP20, OP21, OP23,
OP24, and OP25 breadth remains 31, 34, 22, ten, and five prompts. Across the
full evaluation, 564/3,000 trajectories pass released strict and 551/3,000
pass the raw executable grader, for 97.70% raw executable precision. OP12
index 30 is the recurring benign extra prompt fact, while OP16 index 50 is
genuinely invalid. Counting only the benign row gives 552 semantically valid
trajectories, 97.87% semantic precision, and 12 genuine defects. Issue-code
counts are seven `equation_mismatch`, ten `solver_equation_mismatch`, and two
`unexpected_node`, with overlap. Evaluation has no rollout errors, three
truncations, and mixes adjacent asynchronous policy versions 3099 and 3100.

The preceding train window has released-strict reward 0.4216 and
executable-strict success 0.4156, for 98.59% raw executable precision among
5,396 released passes. Two of three pure `unexpected_node` rows correctly
compute irrelevant prompt-stated facts; the third invents an adult-fox node
in Beverly Forest. Counting the two benign rows gives 5,322 semantically
valid passes, 98.63% semantic precision, and 74 genuine defects. The largest
prompt cluster contributes 22/76 raw mismatches, including false equalities
`8 + 128 = 160` and `160 + 24 = 160`. Issue-code counts are 72
`equation_mismatch`, 23 `solver_equation_mismatch`, three `unexpected_node`,
one `expression_syntax`, and one `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 2.60% and peak transiently at
40.5% on step 3082; none survive into saved rows, whose truncation rate is
0.03%. Mismatch KL stays at most 0.0015 and gradient norm at most 0.4425,
ending at 0.0001 and 0.0193. The step-3100 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3125 records 26.05% on OP11–20 and 12.83% on OP15–20, while OP21–25
is 2.80%. OP20 scores 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout checkpoint uncertainty. OP21, OP22,
OP23, OP24, and OP25 score 6.0%, 4.0%, 3.0%, 0.5%, and 0.5%, respectively.

The sole OP25 pass, new index 85, is manually verified through Hawkesbury
total 2, Glenfield total 6, Brightford total 17, and Evervale total 22 to
Westhaven answer 23. Cumulative executable OP25 breadth therefore rises to
six prompts; OP20–24 breadth remains 31, 34, 30, 22, and ten prompts. Across
the full evaluation, 549/3,000 trajectories pass released strict and
533/3,000 pass the raw executable grader, for 97.09% raw executable
precision. OP12 index 30 is a benign extra prompt fact; the OP13 and OP16
pure-extra-node rows are invalid. Counting only the benign row gives 534
semantically valid trajectories, 97.27% semantic precision, and 15 genuine
defects. Issue-code counts are ten `equation_mismatch`, 12
`solver_equation_mismatch`, and three `unexpected_node`, with overlap.
Evaluation has no rollout errors, eight truncations, and mixes adjacent
asynchronous policy versions 3124 and 3125.

The preceding train window has released-strict reward 0.3630 and
executable-strict success 0.3523, for 97.07% executable precision among 4,646
released passes. The sole pure `unexpected_node` row invents an unstated
Saint-Rivage drama node, so all 136 mismatches are substantive. The largest
prompt cluster contributes 20/136 defects by changing `16*x + 27` to
`18*x + 27`, propagating the total from `24*x + 39` to `26*x + 39`, and then
forcing answer 3. Issue-code counts are 86 `equation_mismatch`, 106
`solver_equation_mismatch`, 14 `undefined_symbol`, and one
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.63% and peak transiently at
15.8% on step 3114; none survive into saved rows, whose truncation rate is
0.06%. Mismatch KL stays at most 0.0047 and gradient norm at most 0.4780,
ending at 0.0004 and 0.0134. The step-3125 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3150 holds OP11–20 at 26.40% and OP15–20 at 12.67%, while OP21–25 is
2.80%. OP20 scores 5.50% on both released and executable strict, 0.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout uncertainty. OP21, OP22, OP23, OP24,
and OP25 score 5.0%, 4.0%, 4.5%, 0.5%, and 0.0%, respectively. No new
executable OP20–25 prompt appears, so cumulative breadth remains 31, 34, 30,
22, ten, and six prompts.

Across the full evaluation, 556/3,000 trajectories pass released strict and
545/3,000 pass the raw executable grader, for 98.02% raw executable
precision. OP12 index 30 is a benign extra prompt fact; the OP13 and OP17
pure-extra-node rows are invalid. Counting only the benign row gives 546
semantically valid trajectories, 98.20% semantic precision, and ten genuine
defects. Issue-code counts are seven `solver_equation_mismatch`, three each
of `equation_mismatch` and `unexpected_node`, and one each of
`unsupported_expression` and `expression_syntax`, with overlap. Evaluation
has no rollout errors, seven truncations, and mixes adjacent asynchronous
policy versions 3149 and 3150.

The preceding train window has released-strict reward 0.4012 and
executable-strict success 0.3755, for 93.59% executable precision among 5,135
released passes. All 329 mismatches are substantive, but three prompts
contribute 251 of them. Their repeated defects include treating `4*x + 4*x`
as `9*x`, dropping one entity from a total, and changing `22*x = 66` to
`22*x = 60` before forcing the correct answer. Issue-code counts are 290
`solver_equation_mismatch`, 78 `equation_mismatch`, two `unexpected_node`,
and one `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 2.90% and peak transiently at
30.8% on step 3149; none survive into saved rows, whose truncation rate is
0.06%. Mismatch KL stays at most 0.0003 and gradient norm at most 0.6337,
ending at 0.0003 and 0.0719. The step-3150 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3175 sets a new OP11–20 run high of 26.85%, with OP15–20 at 12.67% and
OP21–25 at 2.90%. OP20 scores 7.00% on both released and executable strict,
2.266 percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1, though the RL checkpoint still has only one rollout per
prompt. OP21, OP22, OP23, OP24, and OP25 score 7.0%, 4.5%, 2.5%, 0.5%, and
0.0%, respectively. No new executable OP20–25 prompt appears, so cumulative
breadth stays at 31, 34, 30, 22, ten, and six prompts.

Across the full evaluation, 566/3,000 trajectories pass released strict and
554/3,000 pass the raw executable grader, for 97.88% raw executable
precision. The OP11 and OP12 pure-extra-node rows correctly compute
irrelevant prompt facts; the OP13 and OP16 rows are invalid. Counting the two
benign rows gives 556 semantically valid trajectories, 98.23% semantic
precision, and ten genuine defects. Issue-code counts are six
`equation_mismatch`, five `solver_equation_mismatch`, four `unexpected_node`,
and one each of `definition_dependency_mismatch` and
`definition_value_mismatch`, with overlap. Evaluation has no rollout errors,
nine truncations, and mixes adjacent asynchronous policy versions 3174 and
3175.

The preceding train window has released-strict reward 0.4273 and
executable-strict success 0.4186, for 97.97% executable precision among 5,469
released passes. All 111 mismatches are substantive. The largest prompt
cluster contributes 41 defects by changing `6*x + 12` to `9*x + 12`, then
propagating the total to `11*x + 12` before forcing answer 1. Issue-code
counts are 96 `equation_mismatch`, 63 `solver_equation_mismatch`, 13
`undefined_symbol`, and one each of `definition_value_mismatch` and
`expression_syntax`, with overlap.

Logged off-policy cancellation errors average 0.60% and peak transiently at
15.0% on step 3167; none survive into saved rows, whose truncation rate is
0.03%. Mismatch KL stays at most 0.0021 and gradient norm at most 0.7555,
ending at 0.0008 and 0.3509. The step-3175 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3200 records 26.05% on OP11–20 and 12.42% on OP15–20, while OP21–25
is 3.00%. OP20 scores 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout uncertainty. OP21, OP22, OP23, OP24,
and OP25 score 6.0%, 5.0%, 2.5%, 1.5%, and 0.0%, respectively.

New executable-strict OP22 index 76 is manually verified through Glenfield
total 4 and Westhaven total 6 to Hawkesbury answer 13, raising cumulative
OP22 breadth to 31 prompts. Other cumulative OP20, OP21, OP23, OP24, and OP25
breadth stays at 31, 34, 22, ten, and six prompts. Across the full evaluation,
551/3,000 trajectories pass released strict and 542/3,000 pass the raw
executable grader, for 98.37% raw executable precision. The OP11 and OP12
pure-extra-node rows correctly compute irrelevant prompt facts; the OP14 row
uses the wrong total and is invalid. Counting the two benign rows gives 544
semantically valid trajectories, 98.73% semantic precision, and seven genuine
defects. Issue-code counts are five each of `equation_mismatch` and
`solver_equation_mismatch` and three `unexpected_node`, with overlap.
Evaluation has no rollout errors, six truncations, and mixes adjacent
asynchronous policy versions 3199 and 3200.

The preceding train window has released-strict reward 0.3561 and
executable-strict success 0.3373, for 94.73% executable precision among 4,558
released passes. Manual inspection confirms that all three pure
`unexpected_node` rows use an invented node or a wrong dependency, so all
240 mismatches are substantive. The largest prompt cluster contributes 86
defects, repeatedly changing `40*x + 15` to `40*x + 27` and propagating
further false equalities before forcing answer 1. Issue-code counts are 232
`equation_mismatch`, 194 `solver_equation_mismatch`, and three
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.64% and peak transiently at
23.1% on step 3185; none survive into saved rows, whose truncation rate is
0.16%. Mismatch KL stays at most 0.0027 and gradient norm at most 0.2843,
ending at 0.0027 and 0.1291. The step-3200 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3225 ties the OP11–20 run high at 26.85% and raises OP15–20 to 13.67%,
while OP21–25 is 3.30%. OP20 scores 6.00% on both released and executable
strict, 1.266 percentage points above the matched strict-filter OP20 SFT
checkpoint's 4.734% pass@1 but within single-rollout uncertainty. OP21,
OP22, OP23, OP24, and OP25 score 7.0%, 6.0%, 3.0%, 0.0%, and 0.5%,
respectively. The OP25 pass repeats known index 85, and no new executable
OP20–25 prompt appears; cumulative breadth remains 31, 34, 31, 22, ten, and
six prompts.

Across the full evaluation, 570/3,000 trajectories pass released strict and
558/3,000 pass the raw executable grader, for 97.89% raw executable
precision. OP12 index 30 is the recurring benign extra prompt fact; the OP13
and OP16 pure-extra-node rows are invalid. Counting only the benign row gives
559 semantically valid trajectories, 98.07% semantic precision, and 11
genuine defects. Issue-code counts are seven `solver_equation_mismatch`, five
`equation_mismatch`, and three `unexpected_node`, with overlap. Evaluation
has no rollout errors, five truncations, and mixes adjacent asynchronous
policy versions 3224 and 3225.

The preceding train window has released-strict reward 0.3413 and
executable-strict success 0.3288, for 96.31% raw executable precision among
4,369 released passes. Seven of the 30 pure `unexpected_node` rows correctly
compute irrelevant prompt facts; the other 23 use an invented node or wrong
dependency. Counting the seven benign rows gives 4,215 semantically valid
passes, 96.48% semantic precision, and 154 genuine defects. The largest
prompt cluster contributes 51 raw mismatches, repeatedly duplicating a Ruby
Bay term and changing the correct `38*x` total to `44*x` before forcing
answer 3. Issue-code counts are 111 `solver_equation_mismatch`, 107
`equation_mismatch`, 30 `unexpected_node`, two `undefined_symbol`, and one
`unsupported_expression`, with overlap.

Logged off-policy cancellation errors average 1.96% and peak transiently at
30.7% on step 3202; none survive into saved rows, whose truncation rate is
0.05%. Mismatch KL stays at most 0.0007 and gradient norm at most 0.2800,
ending at 0.0001 and 0.0378. The step-3225 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3250 records 26.20% on OP11–20 and 13.50% on OP15–20, while OP21–25
is 3.10%. OP20 reaches 7.50% on both released and executable strict, 2.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1, though the RL estimate still has only one rollout per prompt.
OP21, OP22, OP23, OP24, and OP25 score 7.0%, 4.5%, 3.0%, 0.5%, and 0.5%,
respectively.

New executable-strict OP20 index 32 is manually verified through West Sahara
total 6 to Taylor answer 24. New OP23 index 10 coherently derives Montreval
total 14 and Clairmont total 47 before Saint-Rivage answer 71. Cumulative
executable breadth therefore rises to 32 OP20 prompts and 23 OP23 prompts;
OP21, OP22, OP24, and OP25 remain at 34, 31, ten, and six prompts. Across the
full evaluation, 555/3,000 trajectories pass released strict and 540/3,000
pass the raw executable grader, for 97.30% raw executable precision. OP12
index 30 is benign; OP12 index 186 invents an Evervale elementary-school
node, and OP16 index 50 remains invalid. Counting only the benign row gives
541 semantically valid trajectories, 97.48% semantic precision, and 14
genuine defects. Issue-code counts are eight each of `equation_mismatch` and
`solver_equation_mismatch` and three `unexpected_node`, with overlap.
Evaluation has no rollout errors, four truncations, and mixes adjacent
asynchronous policy versions 3249 and 3250.

The preceding train window has released-strict reward 0.3660 and
executable-strict success 0.3596, for 98.25% executable precision among 4,685
released passes. All 82 mismatches are substantive. The largest prompt
cluster contributes 21 defects, including false equalities `36 + 44 = 92`
and `92 + 4 = 84` that preserve the correct final answer. Issue-code counts
are 81 `equation_mismatch` and 41 `solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 1.66% and peak transiently at
18.3% on step 3242; none survive into saved rows, whose truncation rate is
0.02%. Mismatch KL stays at most 0.0005 and gradient norm at most 0.4680,
ending at 0.0002 and 0.0546. The step-3250 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3275 eases to 25.40% on OP11–20 and 12.58% on OP15–20, while OP21–25
remains strong at 3.30%. OP20 scores 5.50% on both released and executable
strict, 0.766 percentage points above the matched strict-filter OP20 SFT
checkpoint's 4.734% pass@1 but within single-rollout uncertainty. OP21,
OP22, OP23, OP24, and OP25 score 6.5%, 5.5%, 3.5%, 1.0%, and 0.0%,
respectively. No new executable OP20–25 prompt appears, so cumulative breadth
remains 32, 34, 31, 23, ten, and six prompts.

Across the full evaluation, 541/3,000 trajectories pass released strict and
528/3,000 pass the raw executable grader, for 97.60% raw executable
precision. The OP11 pure-extra-node response correctly computes two
irrelevant prompt facts; the OP14, OP15, and OP16 extra-node responses are
invalid. Counting only the benign row gives 529 semantically valid
trajectories, 97.78% semantic precision, and 12 genuine defects. Issue-code
counts are seven `equation_mismatch`, six `solver_equation_mismatch`, and four
`unexpected_node`, with overlap. Evaluation has no rollout errors, five
truncations, and mixes adjacent asynchronous policy versions 3274 and 3275.

The preceding train window has released-strict reward 0.3791 and
executable-strict success 0.3747, for 98.85% raw executable precision among
4,852 released passes. All five pure `unexpected_node` rows correctly compute
irrelevant prompt-stated facts. Counting them gives 4,801 semantically valid
passes, 98.95% semantic precision, and 51 genuine defects. The largest prompt
cluster contributes 25 raw mismatches by reducing the correct Ruby Bay total
from `9*x + 5` to `5*x + 5` and then forcing answer 3. Issue-code counts are
50 `equation_mismatch`, 32 `solver_equation_mismatch`, six `unexpected_node`,
and two `expression_syntax`, with overlap.

Logged off-policy cancellation errors average 2.07% and peak transiently at
31.1% on step 3270; none survive into saved rows, whose truncation rate is
0.02%. Mismatch KL stays at most 0.0006 and gradient norm at most 0.3038,
ending at 0.0000 and 0.0343. The step-3275 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3300 records 24.60% on OP11–20 and 12.58% on OP15–20, while OP21–25
remains at 3.30%. OP20 scores 6.00% on both released and executable strict,
1.266 percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout uncertainty. OP21, OP22, OP23, OP24,
and OP25 score 6.5%, 3.5%, 4.5%, 1.5%, and 0.5%, respectively. No new
executable OP20–25 prompt appears, so cumulative breadth remains 32, 34, 31,
23, ten, and six prompts.

Across the full evaluation, 525/3,000 trajectories pass released strict and
512/3,000 pass the raw executable grader, for 97.52% raw executable precision.
OP12 index 30 correctly computes an irrelevant prompt fact. The OP13 index 32
response invents a culinarian-school node, OP14 index 55 substitutes the Ruby
Bay total into an equation for Shoreline City, and OP16 index 50 substitutes
the South Zoo bear count for the Mayer Aquarium bear count. Counting only the
benign OP12 row gives 513 semantically valid trajectories, 97.71% semantic
precision, and 12 genuine defects. Issue-code counts are six each of
`equation_mismatch` and `solver_equation_mismatch`, four `unexpected_node`,
and one `undefined_symbol`, with overlap. Evaluation has no rollout errors,
two truncations, and mixes adjacent asynchronous policy versions 3299 and
3300.

The preceding train window has released-strict reward 0.3433 and raw
executable-strict success 0.3064, for 89.26% raw executable precision among
4,394 released passes. Of 103 pure `unexpected_node` rows, 101 correctly
compute the prompt-stated adult-bear fact for one OP11 problem; the other two
misuse the Jefferson Circus crow count in place of the Mayer Aquarium parrot
when computing an extra Jefferson Circus parrot node. Counting the 101 benign
rows gives 4,023 semantically valid
passes, 91.56% semantic precision, and 371 genuine defects. The largest
genuine prompt cluster contributes 119 raw mismatches by changing the correct
Ruby Bay total `39*x + 12` to false symbolic equalities before forcing answer
1. Issue-code counts are 331 `solver_equation_mismatch`, 288
`equation_mismatch`, 103 `unexpected_node`, four `expression_syntax`, two
`undefined_symbol`, and one `unsupported_expression`, with overlap.

Logged off-policy cancellation errors average 0.64% and peak transiently at
15.9% on step 3299; none survive into saved rows, whose truncation rate is
0.07%. Mismatch KL stays at most 0.0030 and gradient norm at most 0.3369,
ending at 0.0002 and 0.0967. The step-3300 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3325 reaches 25.10% on OP11–20 and 12.83% on OP15–20, while OP21–25
holds at 3.30%. OP20 again scores 6.00% on both released and executable
strict, 1.266 percentage points above the matched strict-filter OP20 SFT
checkpoint's 4.734% pass@1 but within single-rollout uncertainty. OP21, OP22,
OP23, OP24, and OP25 score 7.0%, 5.5%, 3.0%, 1.0%, and 0.0%, respectively.
No new executable OP20–25 prompt appears, so cumulative breadth remains 32,
34, 31, 23, ten, and six prompts.

Across the full evaluation, 535/3,000 trajectories pass released strict and
520/3,000 pass the raw executable grader, for 97.20% raw executable precision.
OP12 index 30 and OP14 index 199 correctly compute irrelevant prompt facts.
OP15 index 188 uses the wrong difference when computing an extra Maple Creek
crow node, while OP16 index 50 again substitutes the South Zoo bear count for
the Mayer Aquarium bear count. Counting the two benign rows gives 522
semantically valid trajectories, 97.57% semantic precision, and 13 genuine
defects. Issue-code counts are eight `solver_equation_mismatch`, seven
`equation_mismatch`, four `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, three truncations, and mixes
adjacent asynchronous policy versions 3324 and 3325.

The preceding train window has released-strict reward 0.3125 and raw
executable-strict success 0.2988, for 95.62% raw executable precision among
4,000 released passes. All 37 pure `unexpected_node` rows are substantive:
34 repeatedly undercompute a Clearwater Bay medical-school node, and the
remaining three use wrong dependencies for extra Pine Ridge, Clearwater Bay,
and Clairmont nodes. The semantic precision therefore remains 95.62%, with
175 genuine defects. The largest prompt cluster contributes 69 raw mismatches
by changing the correct Riverton City total `20*x + 6` to `24*x + 6` before
forcing answer 1. Issue-code counts are 136 `equation_mismatch`, 113
`solver_equation_mismatch`, and 38 `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.89% and peak transiently at
31.2% on step 3324; none survive into saved rows, whose truncation rate is
0.02%. Mismatch KL stays at most 0.0022 and gradient norm at most 0.7491, both
on step 3311, then return to 0.0004 and 0.0373 at step 3325. The step-3325
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows
are complete.

Step 3350 rises to 26.05% on OP11–20 and 13.08% on OP15–20, while OP21–25
remains at 3.30%. OP20 holds at 6.00% on both released and executable strict,
1.266 percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout uncertainty. OP21, OP22, OP23, OP24,
and OP25 score 7.0%, 5.5%, 3.5%, 0.5%, and 0.0%, respectively. No new
executable OP20–25 prompt appears, so cumulative breadth remains 32, 34, 31,
23, ten, and six prompts.

Across the full evaluation, 554/3,000 trajectories pass released strict and
539/3,000 pass the raw executable grader, for 97.29% raw executable precision.
OP12 index 30 correctly computes an irrelevant prompt fact. The OP13 index 32
response invents a culinarian-school node, while OP14 index 55, OP15 index
188, and OP16 index 50 use wrong dependencies in extra nodes. Counting only
the benign OP12 row gives 540 semantically valid trajectories, 97.47% semantic
precision, and 14 genuine defects. Issue-code counts are ten
`solver_equation_mismatch`, five `unexpected_node`, and four
`equation_mismatch`, with overlap. Evaluation has no rollout errors, six
truncations, and mixes adjacent asynchronous policy versions 3349 and 3350.

The preceding train window has released-strict reward 0.3271 and raw
executable-strict success 0.3217, for 98.35% raw executable precision among
4,187 released passes. All 69 mismatches are substantive. The largest prompt
cluster contributes 29 defects by writing `48 + 27 = 99` and then
`99 + 24 = 99`, preserving the correct final answer through compensating
arithmetic errors. Issue-code counts are 64 `equation_mismatch`, 13
`solver_equation_mismatch`, and one `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.26% and peak transiently at
16.1% on step 3349; none survive into saved rows, whose truncation rate is
0.02%. Mismatch KL stays at most 0.0008 and gradient norm at most 0.5035,
ending at 0.0000 and 0.0223. The step-3350 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3375 records 25.95% on OP11–20 and 13.08% on OP15–20, while OP21–25
is 3.00%. OP20 samples 3.00% on both released and executable strict, 1.734
percentage points below the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout uncertainty. OP21, OP22, OP23, OP24,
and OP25 score 6.0%, 4.0%, 3.5%, 1.0%, and 0.5%, respectively.

New executable-strict OP21 index 99 is manually verified through the
Westhaven City total of 16, Glenfield City private-middle and regional-medical
counts of 14 and 8, and the exact Glenfield City total of 28. Cumulative OP21
breadth therefore rises to 35 prompts; OP20 and OP22–25 remain at 32, 31, 23,
ten, and six prompts. Across the full evaluation, 549/3,000 trajectories pass
released strict and 540/3,000 pass the executable grader, for 98.36%
executable precision. All three pure `unexpected_node` rows are substantive:
one invents a Riverton City school node and two use wrong equations for extra
Shoreline City and Beverly Forest nodes. All nine mismatches are therefore
genuine. Issue-code counts are six `solver_equation_mismatch`, three each of
`equation_mismatch` and `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, two truncations, and mixes adjacent
asynchronous policy versions 3374 and 3375.

The preceding train window has released-strict reward 0.3243 and
executable-strict success 0.3122, for 96.27% executable precision among 4,151
released passes. Its sole pure `unexpected_node` row uses the wrong dependency
for an extra Evervale City node, so all 155 mismatches are substantive. The
largest prompt cluster contributes 88 defects by changing the correct
Westhaven City total `48*x + 15` to `48*x + 23` before forcing answer 1.
Issue-code counts are 150 `equation_mismatch`, 119
`solver_equation_mismatch`, and one each of `expression_syntax`,
`undefined_symbol`, and `unexpected_node`, with overlap.

No off-policy cancellation error is logged in this window, and none survives
into saved rows, whose truncation rate is 0.02%. Steps 3360 and 3372 each
initially drop one all-filtered batch, then immediately obtain a trainable
replacement without interrupting progress. Mismatch KL stays at most 0.0008
and gradient norm at most 0.5056, ending at 0.0002 and 0.2625. The step-3375
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows
are complete.

Step 3400 records 25.70% on OP11–20, raises OP15–20 to 13.75%, and raises
OP21–25 to 3.60%. OP20 scores 6.50% on both released and executable strict,
1.766 percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout uncertainty. OP21, OP22, OP23, OP24,
and OP25 score 6.5%, 6.0%, 4.5%, 1.0%, and 0.0%, respectively. No new
executable OP20–25 prompt appears, so cumulative breadth remains 32, 35, 31,
23, ten, and six prompts.

Across the full evaluation, 550/3,000 trajectories pass released strict and
542/3,000 pass the raw executable grader, for 98.55% raw executable precision.
OP12 index 30 correctly computes an irrelevant prompt fact, while the OP16
index 50 extra-node response remains invalid. Counting only the benign OP12
row gives 543 semantically valid trajectories, 98.73% semantic precision, and
seven genuine defects. Issue-code counts are six `equation_mismatch`, five
`solver_equation_mismatch`, and three `unexpected_node`, with overlap.
Evaluation has no rollout errors, 12 truncations, and mixes adjacent
asynchronous policy versions 3399 and 3400.

The preceding train window has released-strict reward 0.3539 and raw
executable-strict success 0.3505, for 99.03% raw executable precision among
4,530 released passes. Both pure `unexpected_node` rows are substantive: one
undercomputes a Clearwater Bay medical-school node and the other invents a
movie-festival node inside a school problem. All 44 mismatches are therefore
genuine. The largest prompt cluster contributes 17 defects through the false
chain `52 + 39 = 67`, `67 + 5 = 84`, and `84 + 52 = 148`, which preserves
the exact answer. Issue-code counts are 41 `equation_mismatch`, 13
`solver_equation_mismatch`, two `unexpected_node`, and one `undefined_symbol`,
with overlap.

Logged off-policy cancellation errors average 1.56% and peak transiently at
22.1% on step 3389, then return to zero from step 3391 onward. None survives
into saved rows, whose truncation rate is 0.02%. Mismatch KL stays at most
0.0007 and gradient norm at most 0.4125, ending at 0.0002 and 0.0378. The
step-3400 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 3425 records 24.60% on OP11–20, 12.25% on OP15–20, and 3.00% on
OP21–25. OP20 scores 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout uncertainty. OP21, OP22, OP23, OP24,
and OP25 score 6.0%, 5.5%, 2.5%, 0.5%, and 0.5%, respectively.

New executable-strict OP21 index 58 coherently solves the unknown Northwood
futuristic-movie count as 2 from its exact total of 36. New OP24 index 88
derives the Ruby Bay and Clearwater Bay totals of 14 and 28, then the exact
Riverton City answer 81. Cumulative breadth therefore rises to 36 OP21 prompts
and 11 OP24 prompts; OP20, OP22, OP23, and OP25 remain at 32, 31, 23, and six
prompts.

Across the full evaluation, 522/3,000 trajectories pass released strict and
505/3,000 pass the raw executable grader, for 96.74% raw executable precision.
OP12 index 30, OP13 index 54, and OP14 index 199 correctly compute irrelevant
prompt facts; the OP16 index 50 extra-node response remains invalid. Counting
the three benign rows gives 508 semantically valid trajectories, 97.32%
semantic precision, and 14 genuine defects. Issue-code counts are 12
`solver_equation_mismatch`, five `equation_mismatch`, four `unexpected_node`,
and one `undefined_symbol`, with overlap. Evaluation has no rollout errors,
three truncations, and mixes adjacent asynchronous policy versions 3424 and
3425.

The preceding train window has released-strict reward 0.3875 and raw
executable-strict success 0.3677, for 94.88% raw executable precision among
4,960 released passes. Of 96 pure `unexpected_node` rows, 80 correctly compute
an irrelevant Hawkesbury school fact and seven correctly compute irrelevant
movie totals; the remaining nine use the wrong dependency for a Cedar Valley
crow node. Counting the 87 benign rows gives 4,793 semantically valid passes,
96.63% semantic precision, and 167 genuine defects. The largest genuine
prompt cluster contributes 39 mismatches by changing the correct Mayer
Aquarium total `13*x + 32` to `25*x + 32` before forcing answer 2. Issue-code
counts are 141 `equation_mismatch`, 122 `solver_equation_mismatch`, 98
`unexpected_node`, and three `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 0.78% and peak transiently at
19.4% on step 3407; none survives into saved rows, whose truncation rate is
0.16%. Mismatch KL stays at most 0.0008 and gradient norm at most 0.3939,
ending at 0.0002 and 0.1221. The step-3425 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3450 records 24.40% on OP11–20, 13.00% on OP15–20, and 2.90% on
OP21–25. OP20 scores 5.50% on both released and executable strict, 0.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout uncertainty. OP21, OP22, OP23, OP24,
and OP25 score 6.5%, 5.5%, 2.0%, 0.5%, and 0.0%, respectively. No new
executable OP20–25 prompt appears, so cumulative breadth remains 32, 36, 31,
23, 11, and six prompts.

Across the full evaluation, 517/3,000 trajectories pass released strict and
507/3,000 pass the raw executable grader, for 98.07% raw executable precision.
OP13 index 54 correctly computes an irrelevant prompt total; the OP14 index 55
and OP16 index 50 extra-node responses remain invalid. Counting only the
benign OP13 row gives 508 semantically valid trajectories, 98.26% semantic
precision, and nine genuine defects. Issue-code counts are five
`solver_equation_mismatch`, four `equation_mismatch`, and three
`unexpected_node`, with overlap. Evaluation has no rollout errors, one
truncation, and mixes asynchronous policy versions 3449, 3450, and 3451.

The preceding train window has released-strict reward 0.4080 and raw
executable-strict success 0.3965, for 97.19% raw executable precision among
5,222 released passes. Its sole pure `unexpected_node` row correctly computes
an irrelevant prompt fact. Counting it gives 5,076 semantically valid passes,
97.20% semantic precision, and 146 genuine defects. The largest prompt
cluster contributes 95 raw mismatches by changing the correct Ruby Bay total
`39*x + 12` to false symbolic equalities such as `39*x + 32` before forcing
answer 1. Issue-code counts are 141 `equation_mismatch`, 100
`solver_equation_mismatch`, and one `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 3.16% and peak transiently at
29.2% on step 3432; none survives into saved rows, whose truncation rate is
0.15%. Mismatch KL stays at most 0.0013 and gradient norm at most 0.2051,
ending at 0.0008 and 0.0205. The step-3450 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3475 records 23.40% on OP11–20, 11.92% on OP15–20, and 3.40% on
OP21–25. OP20 scores 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout uncertainty. OP21, OP22, OP23, OP24,
and OP25 score 7.0%, 5.0%, 3.0%, 1.5% released/1.0% executable, and 0.5%,
respectively.

New executable-strict OP25 index 20 is manually verified through the
Saint-Rivage and Montreval totals of 21 and 28 to the exact Lumière de Valmont
answer 80. Cumulative OP25 breadth therefore rises to seven prompts; OP20–24
remain at 32, 36, 31, 23, and 11 prompts. Across the full evaluation,
502/3,000 trajectories pass released strict and 489/3,000 pass the raw
executable grader, for 97.41% raw executable precision. OP13 index 54
correctly computes an irrelevant prompt total, while OP14 index 55 remains
invalid. Counting only the benign OP13 row gives 490 semantically valid
trajectories, 97.61% semantic precision, and 12 genuine defects. Issue-code
counts are ten `solver_equation_mismatch`, six `equation_mismatch`, two
`unexpected_node`, and one `undefined_symbol`, with overlap. Evaluation has
no rollout errors, one truncation, and mixes adjacent asynchronous policy
versions 3474 and 3475.

The preceding train window has released-strict reward 0.3597 and raw
executable-strict success 0.3378, for 93.92% raw executable precision among
4,604 released passes. Of 81 pure `unexpected_node` rows, 80 correctly compute
an irrelevant Oakridge Riverside bear fact; the remaining row uses a wrong
dependency for an Oakbridge City medical-school node. Counting the 80 benign
rows gives 4,404 semantically valid passes, 95.66% semantic precision, and 200
genuine defects. The largest genuine prompt cluster contributes 118 raw
mismatches by changing the correct Bundle Ranch total `23*x + 48` to
`32*x + 48` before forcing answer 3. Issue-code counts are 186
`solver_equation_mismatch`, 175 `equation_mismatch`, 82 `unexpected_node`,
nine `undefined_symbol`, and one `expression_syntax`, with overlap.

Logged off-policy cancellation errors average 0.72% and peak transiently at
18.1% on step 3457; none survives into saved rows, whose truncation rate is
0.02%. Mismatch KL stays at most 0.0003 and gradient norm at most 0.4811,
ending at 0.0001 and 0.0474. The step-3475 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3500 records 23.75% on OP11–20, 13.08% on OP15–20, and 2.90% on
OP21–25. OP20 reaches 9.00% on both released and executable strict, 4.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1, although the checkpoint still uses only one rollout per held-out
prompt. OP21, OP22, OP23, OP24, and OP25 score 5.5%, 4.0%, 3.0%, 1.0%, and
1.0%, respectively.

New executable-strict OP20 index 84 is manually verified through the
Montreval total of 12 to the exact Belleville total of 116. New OP21 index 68
derives the Evervale and Westhaven totals of 12 and 31, and new OP24 index 31
derives the Golden Banana and Taylor totals of 9 and 25 before the exact Verdi
answer 84. Cumulative breadth therefore rises to 33 OP20 prompts, 37 OP21
prompts, and 12 OP24 prompts; OP22, OP23, and OP25 remain at 31, 23, and seven
prompts.

Across the full evaluation, 504/3,000 trajectories pass released strict and
492/3,000 pass the executable grader, for 97.62% executable precision. All 12
mismatches are substantive. Issue-code counts are eight
`solver_equation_mismatch`, six `equation_mismatch`, and one
`undefined_symbol`, with overlap. Evaluation has no rollout errors, three
truncations, and mixes adjacent asynchronous policy versions 3499 and 3500.

The preceding train window has released-strict reward 0.3882 and
executable-strict success 0.3796, for 97.79% executable precision among 4,969
released passes. All 110 mismatches are substantive. The largest prompt
cluster contributes 33 defects by changing the correct Bundle Ranch total
`15*x + 32` to `17*x + 32` before forcing answer 2. Issue-code counts are 103
`equation_mismatch` and 91 `solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 1.70% and peak transiently at
24.1% on step 3482; none survives into saved rows, whose truncation rate is
0.01%. Mismatch KL stays at most 0.0034 and gradient norm at most 0.2269,
ending at 0.0000 and 0.0572. The step-3500 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3525 records 24.65% on OP11–20 and 12.33% on OP15–20, while OP21–25
sets a new run high of 4.20%. OP20 scores 5.50% on both released and
executable strict, 0.766 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1 but within single-rollout uncertainty.
OP21, OP22, OP23, OP24, and OP25 score 8.5% released/8.0% executable, 5.0%,
5.0%, 1.5%, and 1.0%, respectively.

New executable-strict OP21 index 32 is manually verified through the
Belleville total of 10 to the exact Saint-Rivage total of 31. Cumulative OP21
breadth therefore rises to 38 prompts; OP20 and OP22–25 remain at 33, 31, 23,
12, and seven prompts. Across the full evaluation, 535/3,000 trajectories pass
released strict and 520/3,000 pass the raw executable grader, for 97.20% raw
executable precision. OP13 index 54 correctly computes an irrelevant prompt
total, while OP13 index 32 invents a graph node. Counting only the benign row
gives 521 semantically valid trajectories, 97.38% semantic precision, and 14
genuine defects. Issue-code counts are ten `solver_equation_mismatch`, nine
`equation_mismatch`, two `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, two truncations, and mixes adjacent
asynchronous policy versions 3524 and 3525.

The preceding train window has released-strict reward 0.4083 and raw
executable-strict success 0.3978, for 97.44% raw executable precision among
5,226 released passes. One pure `unexpected_node` row correctly computes a
Brightford prompt fact; three others invent animal nodes. Counting the one
benign row gives 5,093 semantically valid passes, 97.45% semantic precision,
and 133 genuine defects. The largest prompt cluster contributes 64 raw
mismatches by duplicating a Ruby Bay school node and changing the correct
total `38*x` to `44*x` before forcing answer 3. Issue-code counts are 101
`solver_equation_mismatch`, 79 `equation_mismatch`, 13 `undefined_symbol`,
four `unexpected_node`, and one `definition_value_mismatch`, with overlap.

Logged off-policy cancellation errors average 1.66% and peak transiently at
23.9% on step 3506; none survives into saved rows, which have no truncations.
Mismatch KL stays at most 0.0008 and gradient norm at most 0.3800, ending at
0.0003 and 0.0219. The step-3525 trainer and orchestrator checkpoints, eight
distributed trainer shards, stable inference weights, 512 training rows, and
all 3,000 evaluation rows are complete.

Step 3550 records 24.10% on OP11–20, 12.17% on OP15–20, and 3.30% on
OP21–25. OP20 scores 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1 but within single-rollout uncertainty. OP21, OP22, OP23, OP24,
and OP25 score 4.5%, 6.5%, 3.5%, 1.5%, and 0.5%, respectively.

New executable-strict OP22 index 85 is manually verified through the Riverton
City and Clearwater Bay totals of 12 and 26 to the exact Ruby Bay total 66.
New OP24 index 5 derives the Northwood and West Sahara totals of 7 and 18
before the exact Golden Banana answer 35. Cumulative breadth therefore rises
to 32 OP22 prompts and 13 OP24 prompts; OP20, OP21, OP23, and OP25 remain at
33, 38, 23, and seven prompts.

Across the full evaluation, 515/3,000 trajectories pass released strict and
505/3,000 pass the executable grader, for 98.06% executable precision. All ten
mismatches are substantive. Issue-code counts are six
`solver_equation_mismatch`, four `equation_mismatch`, and one
`unexpected_node`, with overlap. Evaluation has no rollout errors, four
truncations, and mixes adjacent asynchronous policy versions 3549 and 3550.

The preceding train window has released-strict reward 0.4384 and
executable-strict success 0.4221, for 96.28% executable precision among 5,612
released passes. Its pure `unexpected_node` row and the remaining 208
mismatches are all substantive. The largest prompt cluster contributes 73
defects by reversing a subtraction and then writing `2 * -2 = 4`, preserving
the exact answer through a compensating sign error. Issue-code counts are 203
`equation_mismatch`, 84 `solver_equation_mismatch`, two `unexpected_node`, and
one `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.88% and peak transiently at
17.9% on step 3527; none survives into saved rows, whose truncation rate is
0.01%. Mismatch KL stays at most 0.0012 and gradient norm at most 0.7529,
ending at 0.0003 and 0.0976. The step-3550 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3575 records 23.70% on OP11–20, 12.17% on OP15–20, and 3.00% on
OP21–25. OP20 scores 5.50% released strict, 0.766 percentage points above the
matched strict-filter OP20 SFT checkpoint's 4.734% pass@1. Executable strict
removes one false equality and scores 5.00%, 0.266 points above the SFT
reference. The last ten RL checkpoints average 5.90% released strict and
5.85% executable strict on OP20, modestly above 4.734%, but these evaluations
reuse the same 200 prompts, change policy between checkpoints, and draw only
one trajectory per prompt. A matched 128-rollout evaluation of a fixed RL
checkpoint is still required to establish superiority. OP21, OP22, OP23,
OP24, and OP25 score 7.5%, 4.5%, 2.5%, 0.0%, and 0.5%, respectively. No new
executable-strict OP20–25 prompt appears, so cumulative breadth remains 33,
38, 32, 23, 13, and seven prompts.

Across the full evaluation, 504/3,000 trajectories pass released strict and
495/3,000 pass the raw executable grader, for 98.21% raw executable precision.
The extra Golden Banana fact at OP12 index 30 and extra Festival de Clairmont
total at OP13 index 54 are both correct irrelevant prompt facts. The extra
Shoreline City node at OP14 index 55 uses Ruby Bay's total in place of
Shoreline City's, and the extra Mayer Aquarium node at OP16 index 50 uses the
South Zoo bear count in place of Mayer Aquarium's. Counting only the two
benign rows gives 497 semantically valid trajectories, 98.61% semantic
precision, and seven genuine defects. The OP20 released-only trajectory at
index 71 writes `t = E + E = 36 + 13 = 49`, although `E + E` is 26. Issue-code
counts are four `unexpected_node`, three `solver_equation_mismatch`, and two
`equation_mismatch`, with overlap. Evaluation has no rollout errors, three
truncations, and mixes adjacent asynchronous policy versions 3574 and 3575.

The preceding train window has released-strict reward 0.4918 and
executable-strict success 0.4835, for 98.32% executable precision among 6,295
released passes. All 106 mismatches are substantive. The largest prompt
cluster contributes 34 defects by changing the correct symbolic total
`x + 45` to `x + 33`, then retaining the forced solution `x = 4`. Issue-code
counts are 84 `equation_mismatch`, 62 `solver_equation_mismatch`, two each of
`definition_dependency_mismatch` and `definition_value_mismatch`, and one
`undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.11% and peak transiently at
21.7% on step 3562; none survives into saved rows, whose truncation rate is
0.02%. Mismatch KL stays at most 0.0016 and gradient norm at most 0.5477,
ending at 0.0016 and 0.5242. The step-3575 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3600 records 24.10% on OP11–20, 13.25% on OP15–20, and 3.50% on
OP21–25. OP20 reaches 8.50% on both released and executable strict, 3.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint OP20 mean is now 6.15%
released strict and 6.10% executable strict. This is increasingly suggestive
that RL is ahead, but the checkpoint evaluations reuse 200 prompts with one
sample each and the step-3600 value was observed after repeated checkpoint
inspection; a fixed-checkpoint 128-rollout evaluation remains the appropriate
confirmatory comparison. OP21, OP22, OP23, OP24, and OP25 score 8.5%, 4.5%,
3.5%, 1.0%, and 0.0%, respectively.

New executable-strict OP20 index 1 is manually verified through Shoreline
City total 6 and Clearwater Bay total 30 to the exact Ruby Bay answer 120.
Cumulative OP20 breadth therefore rises to 34 prompts; OP21–25 remain at 38,
32, 23, 13, and seven prompts. Across the full evaluation, 517/3,000
trajectories pass released strict and 506/3,000 pass the raw executable
grader, for 97.87% raw executable precision. OP12 index 30 correctly computes
an irrelevant Golden Banana fact, so counting that benign row gives 507
semantically valid trajectories, 98.07% semantic precision, and ten genuine
defects. Issue-code counts are eight `solver_equation_mismatch`, six
`equation_mismatch`, one `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, three truncations, and mixes
adjacent asynchronous policy versions 3599 and 3600.

The preceding train window has released-strict reward 0.3544 and
executable-strict success 0.3492, for 98.54% executable precision among 4,536
released passes. All 66 mismatches are substantive. The largest prompt
cluster contributes 18 defects by writing `72 + 3 = 81` and then
`81 + 24 = 99`; the two compensating arithmetic errors preserve the exact
answer 99. Issue-code counts are 60 `equation_mismatch` and 32
`solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 3.32% and peak transiently at
34.0% on step 3579; none survives into saved rows, whose truncation rate is
0.05%. Mismatch KL has one isolated 0.0084 spike at step 3577, remains at most
0.0025 afterward, and ends at zero. Gradient norm stays at most 0.2815 and
ends at 0.0202. No NaN, OOM, NCCL, or persistent rollout failure appears.
The step-3600 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 3625 records 24.45% on OP11–20, 12.50% on OP15–20, and 3.70% on
OP21–25. OP20 scores 5.00% on both released and executable strict, 0.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint OP20 mean rises to 6.35%
released strict and 6.30% executable strict. OP21, OP22, OP23, OP24, and OP25
score 6.5%, 6.0%, 5.0%, 1.0%, and 0.0%, respectively. All current
executable-strict OP20–24 positives repeat known prompts, so cumulative
breadth remains 34, 38, 32, 23, 13, and seven prompts through OP25.

Across the full evaluation, 526/3,000 trajectories pass released strict and
516/3,000 pass the raw executable grader, for 98.10% raw executable precision.
OP13 index 54 correctly computes an irrelevant Festival de Clairmont total;
counting that benign row gives 517 semantically valid trajectories, 98.29%
semantic precision, and nine genuine defects. Issue-code counts are six
`solver_equation_mismatch`, three each of `equation_mismatch` and
`undefined_symbol`, and one `unexpected_node`, with overlap. Evaluation has
no rollout errors, three truncations, and mixes adjacent asynchronous policy
versions 3624 and 3625.

The preceding train window has released-strict reward 0.3435 and raw
executable-strict success 0.3225, for 93.88% raw executable precision among
4,397 released passes. Twenty-five pure `unexpected_node` rows correctly
compute irrelevant Hawkesbury facts from the prompt; one other such row uses
Oakbridge City's total in place of Riverton City's when computing a Shoreline
City fact and is invalid. Counting only the 25 benign rows gives 4,153
semantically valid passes, 94.45% semantic precision, and 244 genuine defects.
The largest prompt cluster contributes 112 defects by changing the correct
symbolic total `7*x + 13` to `6*x + 13`, then forcing `x = 1` despite the
displayed equations yielding `7/6`. Issue-code counts are 153
`solver_equation_mismatch`, 109 `equation_mismatch`, and 26
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.13% and peak transiently at
17.4% on step 3611; none survives into saved rows, whose truncation rate is
0.06%. Mismatch KL stays at most 0.0015 and gradient norm at most 0.5310,
ending at 0.0001 and 0.2593. No NaN, OOM, NCCL, or persistent rollout failure
appears. The step-3625 trainer and orchestrator checkpoints, eight distributed
trainer shards, stable inference weights, 512 training rows, and all 3,000
evaluation rows are complete.

Step 3650 reaches 26.25% on OP11–20 and sets a new OP15–20 run high of
14.25%, while OP21–25 is 3.20%. OP20 scores 6.50% on both released and
executable strict, 1.766 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. The rolling last-ten-checkpoint OP20 mean
remains 6.35% released strict and 6.30% executable strict. OP21, OP22, OP23,
OP24, and OP25 score 6.5%, 6.5%, 2.5%, 0.5%, and 0.0%, respectively.

New executable-strict OP20 index 57 is manually verified through the Festival
de Clairmont total of 16 and Festival Lumière de Valmont total of 58 to the
exact Cinéma de Montreval answer 84. Cumulative OP20 breadth therefore rises
to 35 prompts; OP21–25 remain at 38, 32, 23, 13, and seven prompts. Across the
full evaluation, 557/3,000 trajectories pass released strict and 543/3,000
pass the raw executable grader, for 97.49% raw executable precision. OP11
index 152 and OP12 index 30 correctly compute irrelevant prompt facts, while
the other two pure extra-node rows are invalid. Counting the two benign rows
gives 545 semantically valid trajectories, 97.85% semantic precision, and 12
genuine defects. Issue-code counts are seven `equation_mismatch`, six
`solver_equation_mismatch`, four `unexpected_node`, and one `undefined_symbol`,
with overlap. Evaluation has no rollout errors, two truncations, and mixes
adjacent asynchronous policy versions 3649 and 3650.

The preceding train window has released-strict reward 0.4624 and
executable-strict success 0.4477, for 96.81% executable precision among 5,919
released passes. All 189 mismatches are substantive. The largest prompt
cluster contributes 109 defects by changing the correct symbolic total
`20 - x` to `20 - 2*x`, then retaining the forced answer `x = 3` despite its
displayed equations yielding `9/2`. Issue-code counts are 182
`equation_mismatch`, 171 `solver_equation_mismatch`, and two
`expression_syntax`, with overlap.

Logged off-policy cancellation errors average 3.08% and peak transiently at
23.8% on step 3632; none survives into saved rows, which have no truncations.
Mismatch KL stays at most 0.0024 and gradient norm at most 0.3570, ending at
0.0001 and 0.0163. No NaN, OOM, NCCL, or persistent rollout failure appears.
The step-3650 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 3675 sets a new OP11–20 run high of 27.10%, records 14.00% on OP15–20,
and raises OP21–25 to 3.90%. OP20 ties the run's best single-checkpoint value at
9.00% on both released and executable strict, 4.266 percentage points above
the matched strict-filter OP20 SFT checkpoint's 4.734% pass@1. The rolling
last-ten-checkpoint OP20 mean rises to 6.65% released strict and 6.60%
executable strict. OP21, OP22, OP23, OP24, and OP25 score 7.5%, 7.0%, 3.0%,
1.5%, and 0.5%, respectively. Every executable-strict OP20–25 positive repeats
a known prompt, so cumulative breadth remains 35, 38, 32, 23, 13, and seven
prompts. The gain is stronger probability mass on observed solvable pockets,
not new prompt coverage at this checkpoint.

Across the full evaluation, 581/3,000 trajectories pass released strict and
569/3,000 pass the raw executable grader, for 97.93% raw executable precision.
OP14 index 199 correctly computes an irrelevant prompt fact; the other two
pure extra-node rows are invalid. Counting the benign row gives 570
semantically valid trajectories, 98.11% semantic precision, and 11 genuine
defects. Issue-code counts are eight `solver_equation_mismatch`, three each of
`equation_mismatch` and `unexpected_node`, and two `undefined_symbol`, with
overlap. Evaluation has no rollout errors, five truncations, and mixes
adjacent asynchronous policy versions 3674 and 3675.

The preceding train window has released-strict reward 0.3784 and raw
executable-strict success 0.3699, for 97.75% raw executable precision among
4,844 released passes. Its sole pure `unexpected_node` row correctly computes
an irrelevant Jefferson Circus fact, yielding 4,736 semantically valid passes,
97.77% semantic precision, and 108 genuine defects. The largest prompt cluster
contributes 38 defects by changing the correct symbolic total `15*x + 32` to
`17*x + 32`, then retaining the forced answer `x = 4`. Issue-code counts are
105 `equation_mismatch`, 79 `solver_equation_mismatch`, and one each of
`unexpected_node`, `expression_syntax`, and `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 2.22% and peak transiently at
34.3% on step 3671; none survives into saved rows, which have no truncations.
Mismatch KL stays at most 0.0004 and gradient norm at most 0.1896, ending at
0.0002 and 0.0779. No NaN, OOM, NCCL, or persistent rollout failure appears.
The step-3675 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 3700 records 25.55% on OP11–20, 13.00% on OP15–20, and 2.90% on
OP21–25. OP20 scores 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint OP20 mean rises slightly to
6.70% released strict and 6.65% executable strict. OP21, OP22, OP23, OP24,
and OP25 score 5.5%, 5.0%, 4.0%, 0.0%, and 0.0%, respectively. No new
executable-strict OP20–25 prompt appears, so cumulative breadth remains 35,
38, 32, 23, 13, and seven prompts.

Across the full evaluation, 540/3,000 trajectories pass released strict and
526/3,000 pass the raw executable grader, for 97.41% raw executable precision.
OP13 index 54 correctly computes an irrelevant prompt fact; the other two
pure extra-node rows are invalid. Counting the benign row gives 527
semantically valid trajectories, 97.59% semantic precision, and 13 genuine
defects. Issue-code counts are ten `solver_equation_mismatch`, eight
`equation_mismatch`, and three `unexpected_node`, with overlap. Evaluation has
no rollout errors, two truncations, and mixes adjacent asynchronous policy
versions 3699 and 3700.

The preceding train window has released-strict reward 0.3824 and
executable-strict success 0.3770, for 98.59% executable precision among 4,895
released passes. All 69 mismatches are substantive. The largest prompt cluster
contributes 19 defects by writing `36 + 44 = 92` and then `92 + 4 = 84`, two
compensating arithmetic errors that preserve the exact answer. Issue-code
counts are 52 `equation_mismatch`, 35 `solver_equation_mismatch`, and one
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.71% and peak transiently at
17.7% on step 3685; none survives into saved rows, which have no truncations.
Mismatch KL stays at most 0.0007 and gradient norm at most 0.5184, ending at
0.0001 and 0.0218. No NaN, OOM, NCCL, or persistent rollout failure appears.
The step-3700 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 3725 records 26.15% on OP11–20, 12.92% on OP15–20, and 3.50% on
OP21–25. OP20 scores 6.50% on both released and executable strict, 1.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint OP20 mean rises to 6.75%
released strict and 6.70% executable strict. OP21, OP22, OP23, OP24, and OP25
score 6.5%, 7.0%, 3.0%, 1.0%, and 0.0%, respectively.

New executable-strict OP21 index 138 correctly derives Cedar Valley total 7
and Pine Ridge total 19 before the exact Oakridge Riverside answer 25. New
OP21 index 154 derives Oakridge Riverside total 12 and Beverly Forest total 36
before the exact Pine Ridge answer 111. Cumulative OP21 breadth therefore
rises from 38 to 40 prompts; OP20 and OP22–25 remain at 35, 32, 23, 13, and
seven prompts.

Across the full evaluation, 558/3,000 trajectories pass released strict and
542/3,000 pass the raw executable grader, for 97.13% raw executable precision.
OP13 index 54 correctly computes an irrelevant prompt fact; the other two
pure extra-node rows are invalid. Counting the benign row gives 543
semantically valid trajectories, 97.31% semantic precision, and 15 genuine
defects. Issue-code counts are eight `solver_equation_mismatch`, seven
`equation_mismatch`, and three `unexpected_node`, with overlap. Evaluation has
no rollout errors or truncations and mixes adjacent asynchronous policy
versions 3724 and 3725.

The preceding train window has released-strict reward 0.4262 and raw
executable-strict success 0.4127, for 96.85% raw executable precision among
5,455 released passes. One pure `unexpected_node` row correctly computes an
irrelevant Shoreline City fact. Counting it gives 5,284 semantically valid
passes, 96.87% semantic precision, and 171 genuine defects. The largest prompt
cluster contributes 72 invalid extra-node responses by setting the Evervale
City culinarian count to Brightford's total 5, although the prompt defines it
as Westhaven City's total 21. Issue-code counts are 96 `equation_mismatch`, 73
`unexpected_node`, and 54 `solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 1.68% and peak transiently at
23.8% on step 3703; none survives into saved rows, which have no truncations.
Mismatch KL stays at most 0.0027 and gradient norm at most 0.4308, ending at
0.0001 and 0.0341. No NaN, OOM, NCCL, or persistent rollout failure appears.
The step-3725 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 3750 records 27.00% on OP11–20 and sets a new OP15–20 run high of
15.33%, while OP21–25 is 3.30%. OP20 scores 7.50% on both released and
executable strict, 2.766 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. The rolling last-ten-checkpoint OP20 mean
is 6.60% released strict and 6.55% executable strict. OP21, OP22, OP23, OP24,
and OP25 score 6.5%, 6.0%, 2.5%, 1.5%, and 0.0%, respectively. No new
executable-strict OP20–25 prompt appears, so cumulative breadth remains 35,
40, 32, 23, 13, and seven prompts.

Across the full evaluation, 573/3,000 trajectories pass released strict and
564/3,000 pass the raw executable grader, for 98.43% raw executable precision.
OP11 index 152 and OP13 index 54 correctly compute irrelevant prompt facts;
the other two pure extra-node rows are invalid. Counting the two benign rows
gives 566 semantically valid trajectories, 98.78% semantic precision, and
seven genuine defects. Issue-code counts are four each of
`solver_equation_mismatch` and `unexpected_node`, and three
`equation_mismatch`, with overlap. Evaluation has no rollout errors, four
truncations, and mixes adjacent asynchronous policy versions 3749 and 3750.

The preceding train window has released-strict reward 0.3654 and raw
executable-strict success 0.3599, for 98.50% raw executable precision among
4,677 released passes. Three pure `unexpected_node` rows correctly compute an
irrelevant Clearwater Bay fact. Counting them gives 4,610 semantically valid
passes, 98.57% semantic precision, and 67 genuine defects. The largest prompt
cluster contributes 16 defects by changing the correct symbolic total
`16*x + 31` to `16*x + 23`, then retaining the forced answer `x = 4`. Issue-code
counts are 52 `equation_mismatch`, 45 `solver_equation_mismatch`, and three
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 2.48% and peak transiently at
32.3% on step 3750; none survives into saved rows, which have no truncations.
Mismatch KL stays at most 0.0007 and gradient norm at most 0.1567, ending at
zero and 0.0215. No NaN, OOM, NCCL, or persistent rollout failure appears.
The step-3750 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 3775 records 26.60% on OP11–20, 13.75% on OP15–20, and 3.60% on
OP21–25. OP20 again scores 7.50% on both released and executable strict,
2.766 percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint OP20 mean is now 6.80%
released strict and 6.75% executable strict. OP21, OP22, OP23, OP24, and OP25
score 7.5%, 6.0%, 3.0%, 1.0%, and 0.5%, respectively. No new
executable-strict OP20–25 prompt appears, so cumulative breadth remains 35,
40, 32, 23, 13, and seven prompts.

Across the full evaluation, 568/3,000 trajectories pass released strict and
560/3,000 pass the raw executable grader, for 98.59% raw executable precision.
The only pure extra-node rejection, OP12 index 30, correctly computes the
irrelevant Golden Banana calm-road count as 12. Counting it gives 561
semantically valid trajectories, 98.77% semantic precision, and seven genuine
defects. Issue-code counts are five each of `equation_mismatch` and
`solver_equation_mismatch`, one `undefined_symbol`, and one `unexpected_node`,
with overlap. Evaluation has no rollout errors, six truncations, and every
shard mixes adjacent asynchronous policy versions 3774 and 3775.

The preceding train window has released-strict reward 0.3108 and raw
executable-strict success 0.3100, for 99.75% executable precision among 3,978
released passes. Both pure `unexpected_node` rows are genuine defects on the
same prompt: they introduce adult parrot in Jefferson Circus but compute it as
4 by subtracting the wrong source value; the prompt implies 5. The raw and
semantic counts therefore agree at 3,968 valid passes and ten genuine defects.
Issue-code counts are eight `equation_mismatch`, two
`solver_equation_mismatch`, and two `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.02% and occur only at step
3768, where they peak transiently at 25.4%; none survives into saved rows,
which have no errors and one truncation. Mismatch KL stays at most 0.0005 and
gradient norm at most 0.3806, ending at 0.0001 and 0.1932. No NaN, OOM, NCCL,
or persistent rollout failure appears. The step-3775 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3800 records 26.90% on OP11–20, 14.42% on OP15–20, and 3.40% on
OP21–25. OP20 scores 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint OP20 mean remains 6.80%
released strict and 6.75% executable strict. OP21, OP22, OP23, OP24, and OP25
score 5.5%, 6.0%, 3.5%, 1.0%, and 1.0%, respectively. No new
executable-strict OP20–25 prompt appears, so cumulative breadth remains 35,
40, 32, 23, 13, and seven prompts.

Across the full evaluation, 572/3,000 trajectories pass released strict and
557/3,000 pass the raw executable grader, for 97.38% raw executable precision.
OP11 index 152 and OP12 index 30 correctly compute irrelevant prompt facts;
the other four pure extra-node rows are invalid. Counting the two benign rows
gives 559 semantically valid trajectories, 97.73% semantic precision, and 13
genuine defects. Issue-code counts are six each of
`solver_equation_mismatch` and `unexpected_node`, and five
`equation_mismatch`, with overlap. Evaluation has no rollout errors, six
truncations, and every shard mixes asynchronous policy versions 3799–3801.

The preceding train window has released-strict reward 0.3851 and raw
executable-strict success 0.3712, for 96.39% raw executable precision among
4,929 released passes. One pure extra-node row correctly computes the
irrelevant Cinéma de Montreval futuristic-sci-fi count as 4; two others invent
an unsupported Northwood futuristic-sci-fi relation and are invalid. Counting
the benign row gives 4,752 semantically valid passes, 96.41% semantic
precision, and 177 genuine defects. The three largest prompt clusters account
for 74, 39, and 31 defects. The largest repeatedly writes the correct symbolic
total `19*x + 14` but claims that `x = 2` satisfies a displayed total of 54,
although substitution gives 52. Issue-code counts are 126
`solver_equation_mismatch`, 99 `equation_mismatch`, three `unexpected_node`,
and one `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 0.70% and occur only at step
3789, where they peak transiently at 17.5%; none survives into saved rows,
which have no errors and two truncations. Mismatch KL stays at most 0.0008 and
gradient norm at most 0.1469, ending at zero and 0.0252. No NaN, OOM, NCCL,
or persistent rollout failure appears. The step-3800 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3825 records 26.30% on OP11–20, 14.08% on OP15–20, and 3.60% on
OP21–25. OP20 rises to 9.00% on both released and executable strict, 4.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint OP20 mean is now 7.15% for
both released and executable strict. OP21, OP22, OP23, OP24, and OP25 score
6.5%, 7.0%, 3.0%, 0.5%, and 1.0%, respectively. OP20 index 45 is a new
executable-strict success: it derives Bundle Ranch's total as 11, Jefferson
Circus's total as 59, Hamilton Farm's crow and owl counts as 70 and 8, and the
exact requested total 78. Cumulative OP20 breadth therefore expands to 36
prompts; OP21–25 breadth remains 40, 32, 23, 13, and seven prompts.

Across the full evaluation, 562/3,000 trajectories pass released strict and
557/3,000 pass the executable grader, for 99.11% precision. The sole pure
extra-node row is invalid: OP16 index 50 claims the Mayer Aquarium deer count
is 45 even though the prompt defines it as `3 + 4 = 7`. There are therefore
557 semantically valid trajectories and five genuine defects. Issue-code
counts are three each of `equation_mismatch` and
`solver_equation_mismatch`, and one `unexpected_node`, with overlap.
Evaluation has no rollout errors, five truncations, and every shard mixes
adjacent asynchronous policy versions 3824 and 3825.

The preceding train window has released-strict reward 0.4430 and raw
executable-strict success 0.4216, for 95.17% raw executable precision among
5,670 released passes. Manual review finds that 121 pure extra-node rows all
compute the explicit but irrelevant Mayer Aquarium crow count as 20, and one
more correctly totals the three Rêves de Belleville movie categories as
`4*x`. Three Pine Ridge extra-node rows are invalid. Counting the 122 benign
rows gives 5,518 semantically valid passes, 97.32% semantic precision, and
152 genuine defects. The largest genuine cluster contributes 101 defects by
writing the symbolic total `17*x + 4`, then claiming that `x = 4` satisfies a
displayed total of 76 even though substitution gives 72. Raw issue-code counts
are 125 `unexpected_node`, 123 `solver_equation_mismatch`, 53
`equation_mismatch`, and two `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.68% and occur only at steps
3806 and 3809, where they peak transiently at 24.6% and 17.5%; none survives
into saved rows, which have no errors and one truncation. Mismatch KL stays at
most 0.0002 and gradient norm at most 0.4866, ending at 0.0002 and 0.3149. No
NaN, OOM, NCCL, or persistent rollout failure appears. The step-3825 trainer
and orchestrator checkpoints, eight distributed trainer shards, stable
inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 3850 records 26.45% on OP11–20, 13.83% on OP15–20, and 3.30% on
OP21–25. OP20 repeats 9.00% on both released and executable strict, providing
the first immediate replication of the step-3825 high. Its rolling
last-ten-checkpoint mean rises to 7.20% for both released and executable
strict, compared with 4.734% pass@1 for the matched strict-filter OP20 SFT
checkpoint. OP21, OP22, OP23, OP24, and OP25 score 5.5%, 6.5%, 3.5%, 1.0%,
and 0.0%, respectively. OP22 index 83 is a new executable-strict success: it
derives Oakbridge City's total as 20, Shoreline City's total as 33, and the
requested Ruby Bay culinarian count as 37. Cumulative executable breadth is
now 36, 40, 33, 23, 13, and seven prompts for OP20–25.

Across the full evaluation, 562/3,000 trajectories pass released strict and
551/3,000 pass the executable grader, for 98.04% precision. Both pure
extra-node rows are invalid: OP14 index 55 invents the Shoreline elementary
dependency, while OP16 index 50 again writes the Mayer Aquarium deer count as
45 instead of 7. The semantic count therefore remains 551, with 11 genuine
defects. Issue-code counts are six each of `equation_mismatch` and
`solver_equation_mismatch`, and two `unexpected_node`, with overlap.
Evaluation has no rollout errors, eight truncations, and every shard mixes
adjacent asynchronous policy versions 3849 and 3850.

The preceding train window has released-strict reward 0.4078 and
executable-strict success 0.3993, for 97.91% precision among 5,220 released
passes. There are no pure extra-node cases, so all 109 executable rejections
are genuine defects. The largest prompt cluster contributes 33 defects by
replacing the correct total `25*x + 8` with `19*x + 4`, then retaining the
forced answer `x = 4` even though the displayed expression evaluates to 80
rather than 108. Issue-code counts are 89 `equation_mismatch`, 59
`solver_equation_mismatch`, and one each of `definition_dependency_mismatch`,
`undefined_symbol`, and `unexpected_node`, with overlap.

Logged rollout errors are zero throughout steps 3826–3850, and saved rows
have no errors and three truncations. Mismatch KL stays at most 0.0006 and
gradient norm at most 0.3078, ending at 0.0002 and 0.0545. No NaN, OOM, NCCL,
or persistent rollout failure appears. The step-3850 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3875 records 26.15% on OP11–20, 14.67% on OP15–20, and 3.90% on
OP21–25. OP20 scores 7.50% on both released and executable strict, and its
rolling last-ten-checkpoint mean rises to 7.45% for both measures, compared
with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint. OP21,
OP22, OP23, OP24, and OP25 score 6.5%, 7.5%, 3.5%, 1.5%, and 0.5%,
respectively. No new executable OP20–25 problem appears, so cumulative breadth
remains 36, 40, 33, 23, 13, and seven prompts.

Across the full evaluation, 562/3,000 trajectories pass released strict and
546/3,000 pass the raw executable grader, for 97.15% raw precision. Three
pure extra-node rows correctly compute irrelevant facts: OP11 index 152's
Bundle Ranch crow count, OP13 index 54's Festival de Clairmont total, and
OP15 index 44's Northwood total. Three other pure extra-node rows are invalid.
Counting the benign rows gives 549 semantically valid trajectories, 97.69%
semantic precision, and 13 genuine defects. Issue-code counts are eight
`solver_equation_mismatch`, six `unexpected_node`, four `equation_mismatch`,
and one `undefined_symbol`, with overlap. Evaluation has no rollout errors,
five truncations, and every shard mixes adjacent asynchronous policy versions
3874 and 3875.

The preceding train window sets a new 25-step released-strict reward high of
0.4709 and has raw executable-strict success 0.4628, for 98.27% raw precision
among 6,028 released passes. Fifteen pure extra-node rows correctly compute
irrelevant prompt facts; one incorrectly computes the Jefferson Circus wolf
count as 11 instead of 13. Counting the benign rows gives 5,939 semantically
valid passes, 98.52% semantic precision, and 89 genuine defects. The largest
prompt cluster contributes 15 defects by corrupting the final Beverly Forest
total with reused or undefined symbols; the common form writes `11*x + 10`
and claims `x = 1` satisfies 20, although it evaluates to 21. Issue-code counts
are 65 `equation_mismatch`, 60 `solver_equation_mismatch`, 16
`unexpected_node`, two `undefined_symbol`, and one `expression_syntax`, with
overlap.

Logged off-policy cancellation errors average 1.74% and occur only at steps
3857 and 3871, where they peak transiently at 25.2% and 18.3%; none survives
into saved rows, which have no errors and four truncations. Gradient norm stays
at most 0.3734. Mismatch KL ends at its window maximum of 0.0046, still small
but above recent windows and therefore worth watching at the next checkpoint;
endpoint gradient norm is 0.0212. No NaN, OOM, NCCL, or persistent rollout
failure appears. The step-3875 trainer and orchestrator checkpoints, eight
distributed trainer shards, stable inference weights, 512 training rows, and
all 3,000 evaluation rows are complete.

Step 3900 records 23.80% on OP11–20, 13.50% on OP15–20, and 3.50% on
OP21–25. The OP11–20 aggregate dips from its recent 26% range, but OP20
retains 8.00% on both released and executable strict. Its rolling
last-ten-checkpoint mean rises to 7.60% for both measures, compared with
4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint. OP21, OP22,
OP23, OP24, and OP25 score 5.5%, 6.5%, 3.5%, 1.5%, and 0.5%, respectively.
No new executable OP20–25 problem appears, so cumulative breadth remains 36,
40, 33, 23, 13, and seven prompts.

Across the full evaluation, 511/3,000 trajectories pass released strict and
492/3,000 pass the raw executable grader, for 96.28% raw precision. OP13
index 54 correctly computes the irrelevant Festival de Clairmont total;
OP16 index 50's extra Mayer Aquarium deer count is invalid. Counting the one
benign row gives 493 semantically valid trajectories, 96.48% semantic
precision, and 18 genuine defects. Issue-code counts are 14
`solver_equation_mismatch`, nine `equation_mismatch`, two each of
`undefined_symbol` and `unexpected_node`, and one `expression_syntax`, with
overlap. Evaluation has no rollout errors, three truncations, and every shard
mixes adjacent asynchronous policy versions 3899 and 3900.

The preceding train window has released-strict reward 0.3797 and raw
executable-strict success 0.3752, for 98.83% raw precision among 4,860
released passes. Two pure extra-node rows correctly compute the irrelevant
Clearwater Bay private-middle count, giving 4,805 semantically valid passes,
98.87% semantic precision, and 55 genuine defects. The largest prompt cluster
contributes 25 defects by replacing the correct Maple Creek total
`54*x + 8` with an inconsistent `44*x + 4`, then retaining `x = 1` even
though the displayed expression evaluates to 48 rather than 62. Issue-code
counts are 51 `equation_mismatch`, 49 `solver_equation_mismatch`, two
`unexpected_node`, and one `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.84% and occur only at steps
3878 and 3890, where they peak transiently at 16.8% and 29.3%; none survives
into saved rows, which have no errors and five truncations. Mismatch KL stays
at most 0.0007 and returns to zero at the endpoint, confirming that the
step-3875 increase was transient. Gradient norm stays at most 0.2913 and ends
at 0.0840. No NaN, OOM, NCCL, or persistent rollout failure appears. The
step-3900 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 3925 records 25.15% on OP11–20, 14.33% on OP15–20, and 3.30% on
OP21–25. OP20 scores 6.00% on both released and executable strict, with a
rolling last-ten-checkpoint mean of 7.30% for both measures, compared with
4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint. OP21, OP22,
OP23, OP24, and OP25 score 6.0%, 6.0%, 4.0%, 0.5%, and 0.0%, respectively.
No new executable OP20–25 problem appears, so cumulative breadth remains 36,
40, 33, 23, 13, and seven prompts.

Across the full evaluation, 536/3,000 trajectories pass released strict and
526/3,000 pass the raw executable grader, for 98.13% raw precision. OP12
index 30 correctly computes the irrelevant Golden Banana calm-road count;
OP14 index 55's extra Shoreline elementary dependency is invalid. Counting
the benign row gives 527 semantically valid trajectories, 98.32% semantic
precision, and nine genuine defects. Issue-code counts are seven
`solver_equation_mismatch`, four `equation_mismatch`, and two
`unexpected_node`, with overlap. Evaluation has no rollout errors, four
truncations, and every shard mixes asynchronous policy versions 3924–3926.

The preceding train window has released-strict reward 0.3274 and raw
executable-strict success 0.3088, for 94.30% raw precision among 4,191
released passes. Nine pure extra-node rows correctly compute the irrelevant
Festival de Saint-Rivage total as 4. Counting them gives 3,961 semantically
valid passes, 94.51% semantic precision, and 230 genuine defects. The largest
prompt cluster contributes 86 defects by replacing the correct Westhaven
total `48*x + 15` with an inconsistent `44*x + 15`, then retaining `x = 1`
even though the displayed expression evaluates to 59 rather than 63.
Issue-code counts are 196 `solver_equation_mismatch`, 163
`equation_mismatch`, and nine `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.49% and occur only at step
3914, where they peak transiently at 12.2%; none survives into saved rows,
which have no errors and one truncation. Mismatch KL peaks at 0.0030 on step
3919 and returns to 0.0001 at the endpoint. Gradient norm stays at most 0.1240
and ends at 0.0418. No NaN, OOM, NCCL, or persistent rollout failure appears.
The step-3925 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 3950 records 22.95% on OP11–20, 13.42% on OP15–20, and 3.40% on
OP21–25. OP20 scores 7.50% released strict and 7.00% executable strict. Its
rolling last-ten-checkpoint means are 7.45% released and 7.40% executable,
compared with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint.
OP21, OP22, OP23, OP24, and OP25 score 6.5%, 6.0%, 3.5%, 1.0%, and 0.0%,
respectively. No new executable OP20–25 problem appears, so cumulative breadth
remains 36, 40, 33, 23, 13, and seven prompts.

Across the full evaluation, 493/3,000 trajectories pass released strict and
481/3,000 pass the executable grader, for 97.57% precision. Both pure
extra-node rows are invalid: OP14 index 55 invents the Shoreline elementary
dependency, while OP16 index 50 again writes the Mayer Aquarium deer count as
45 instead of 7. The semantic count therefore remains 481, with 12 genuine
defects. Issue-code counts are nine `solver_equation_mismatch`, seven
`equation_mismatch`, two `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, five truncations, and every shard
mixes adjacent asynchronous policy versions 3949 and 3950.

The preceding train window has released-strict reward 0.4489 and raw
executable-strict success 0.4334, for 96.54% raw precision among 5,746
released passes. Two pure extra-node rows correctly compute the irrelevant
Festival Lumière de Valmont upbeat-comedy count as 16. Counting them gives
5,549 semantically valid passes, 96.57% semantic precision, and 197 genuine
defects. The largest prompt cluster contributes 115 defects. Its common form
writes the correct equation `23*x + 48 = 117`, then subtracts 48 as 60 rather
than 69 while retaining the exact answer `x = 3`. Issue-code counts are 178
`equation_mismatch`, 154 `solver_equation_mismatch`, and two
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 2.30% and occur at steps 3926,
3931, 3944, and 3948, peaking transiently at 18.8%; none survives into saved
rows, which have no errors and two truncations. Mismatch KL stays at most
0.0002 and ends at zero. Gradient norm briefly reaches 0.7481 on step 3948 but
returns to 0.0488 without a NaN or subsequent instability. No OOM, NCCL, or
persistent rollout failure appears. The step-3950 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 3975 records 22.65% on OP11–20, 13.67% on OP15–20, and 3.30% on
OP21–25. OP20 scores 7.00% on both released and executable strict. Its rolling
last-ten-checkpoint means are 7.50% released and 7.45% executable, compared
with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint. OP21,
OP22, OP23, OP24, and OP25 score 7.0%, 5.0%, 4.0%, 0.5%, and 0.0%,
respectively. No new executable OP20–25 problem appears, so cumulative breadth
remains 36, 40, 33, 23, 13, and seven prompts.

Across the full evaluation, 486/3,000 trajectories pass released strict and
474/3,000 pass the executable grader, for 97.53% precision. Both pure
extra-node rows are invalid: OP14 index 55 invents the Shoreline elementary
dependency, while OP16 index 50 again writes the Mayer Aquarium deer count as
45 instead of 7. The semantic count therefore remains 474, with 12 genuine
defects. Issue-code counts are eight `solver_equation_mismatch`, five
`equation_mismatch`, two `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, one truncation, and every shard
mixes adjacent asynchronous policy versions 3974 and 3975.

The preceding train window sets a new 25-step released-strict reward high of
0.4915 and has executable-strict success 0.4755, for 96.74% precision among
6,291 released passes. There are no pure extra-node rows, so all 205
executable rejections are genuine defects. The largest prompt cluster
contributes 121 defects by replacing the correct Glenfield total `7*x + 13`
with `6*x + 13`, then retaining `x = 1` although the displayed expression
evaluates to 19 rather than 20. Issue-code counts are 185
`solver_equation_mismatch`, 30 `equation_mismatch`, and two
`undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.88% and occur at steps 3965,
3968, and 3974, peaking transiently at 22.8%; none survives into saved rows,
which have no errors and one truncation. Mismatch KL peaks at 0.0073 and
remains elevated relative to recent windows at 0.0056 on the endpoint.
Gradient norm peaks at 0.7872 and ends at 0.1366. Both require follow-up at the
next checkpoint, but no NaN, OOM, NCCL, or persistent rollout failure appears.
The step-3975 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4000 rebounds to 26.60% on OP11–20, 14.00% on OP15–20, and 4.10% on
OP21–25. OP20 scores 7.50% on both released and executable strict. Its rolling
last-ten-checkpoint means remain 7.50% released and 7.45% executable, compared
with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint. OP21,
OP22, OP23, OP24, and OP25 score 7.5%, 6.5%, 5.0%, 1.5%, and 0.0%,
respectively. OP21 index 119 is a new executable-strict success: it derives
Ruby Bay's total as 8, Riverton City's total as 16, Clearwater Bay's total as
24, and the exact requested Clearwater public-highschool count 4. Cumulative
OP21 breadth therefore expands to 41; OP20 and OP22–25 remain at 36, 33, 23,
13, and seven prompts.

Across the full evaluation, 573/3,000 trajectories pass released strict and
565/3,000 pass the raw executable grader, for 98.60% raw precision. OP13
index 54 correctly computes the irrelevant Festival de Clairmont total.
Counting it gives 566 semantically valid trajectories, 98.78% semantic
precision, and seven genuine defects. Issue-code counts are six
`equation_mismatch`, five `solver_equation_mismatch`, and one each of
`undefined_symbol` and `unexpected_node`, with overlap. Evaluation has no
rollout errors, two truncations, and every shard mixes adjacent asynchronous
policy versions 3999 and 4000.

The preceding train window has released-strict reward 0.2899 and
executable-strict success 0.2805, for 96.74% precision among 3,711 released
passes. There are no pure extra-node cases, so all 121 executable rejections
are genuine defects. The largest prompt cluster contributes 44 defects by
fabricating intermediate arithmetic such as `52 + 39 = 67` and
`67 + 5 = 84` while retaining the exact final answer 148. Issue-code counts
are 111 `equation_mismatch`, 50 `solver_equation_mismatch`, and one
`expression_syntax`, with overlap.

Logged off-policy cancellation errors average 0.73% and occur only at step
3986, where they peak transiently at 18.3%; none survives into saved rows,
which have no errors and two truncations. Mismatch KL spikes briefly to 0.0487
on step 3984 but returns to 0.0001 at the checkpoint, resolving the concern
from the preceding window. Gradient norm stays at most 0.2904 and ends at
0.1311. No NaN, OOM, NCCL, or persistent rollout failure appears. The
step-4000 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4025 records 26.65% on OP11–20, 13.58% on OP15–20, and 4.00% on
OP21–25. OP20 scores 7.00% on both released and executable strict. Its rolling
last-ten-checkpoint means are 7.45% released and 7.40% executable, compared
with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint. OP21,
OP22, OP23, OP24, and OP25 score 8.0%, 8.0%, 3.0%, 1.0%, and 0.0%,
respectively. All executable OP20–25 positives repeat previously solved
problems, so cumulative breadth remains 36, 41, 33, 23, 13, and seven prompts.

Across the full evaluation, 573/3,000 trajectories pass released strict and
564/3,000 pass the raw executable grader, for 98.43% raw precision. OP13 index
74 adds four correctly computed but irrelevant prompt nodes, including the
Evervale City elementary-school count of 68; counting it gives 565
semantically valid trajectories, 98.60% semantic precision, and eight genuine
defects. The other pure-extra-node cases are substantive: OP16 index 50
computes Mayer Aquarium deer as 45 instead of the prompt-specified 7, and OP17
index 197 invents an ungrounded Mayer Aquarium racoon count. Issue-code counts
are six `solver_equation_mismatch`, three `equation_mismatch`, and three
`unexpected_node`, with overlap. Evaluation has no rollout errors, one
truncation, and every shard mixes adjacent asynchronous policy versions 4024
and 4025.

The preceding train window has released-strict reward 0.3650 and
executable-strict success 0.3533, for 96.79% precision among 4,672 released
passes. There are no pure extra-node cases, so all 150 executable rejections
are genuine defects. Prompt 597 contributes 60 defects by corrupting the
Cedar Valley total from the correct `8*x + 12` to `11*x + 12` while forcing
the gold solution `x = 1`. Prompt 574 contributes another 44 by double-counting
the queried Bundle Ranch deer in the Hamilton Farm total, producing
`12*x + 21` instead of `11*x + 21` while forcing `x = 3`. Issue-code counts
are 136 `equation_mismatch`, 125 `solver_equation_mismatch`, and one
`undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 2.10% and occur only at steps
4004 and 4005, peaking transiently at 30.6%; none survives into saved rows,
which have no errors or truncations. Mismatch KL stays at most 0.0004 and ends
at zero. Gradient norm stays at most 0.2751 and ends at 0.0741. No NaN, OOM,
NCCL, or persistent rollout failure appears. The step-4025 trainer and
orchestrator checkpoints, eight distributed trainer shards, stable inference
weights, 512 training rows, and all 3,000 evaluation rows are complete.

Step 4050 rises to 27.50% on OP11–20 and 14.08% on OP15–20, while OP21–25
falls to 3.20%. OP20 scores 6.50% on both released and executable strict. Its
rolling last-ten-checkpoint means are 7.50% released and 7.45% executable,
compared with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint.
OP21, OP22, OP23, OP24, and OP25 score 6.0%, 5.0%, 3.5%, 1.5%, and 0.0%,
respectively. All executable OP20–25 positives repeat previously solved
problems, so cumulative breadth remains 36, 41, 33, 23, 13, and seven prompts.

Across the full evaluation, 582/3,000 trajectories pass released strict and
566/3,000 pass the raw executable grader, for 97.25% raw precision. OP13 index
54 correctly computes the irrelevant Festival de Clairmont total as 18;
counting it gives 567 semantically valid trajectories, 97.42% semantic
precision, and 15 genuine defects. The other pure-extra-node cases are
substantive: OP14 index 55 substitutes Ruby Bay's total for the unknown
Shoreline City total, and OP16 index 50 again computes Mayer Aquarium deer as
45 instead of 7. Issue-code counts are nine `solver_equation_mismatch`, eight
`equation_mismatch`, three `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, two truncations, and every shard
mixes adjacent asynchronous policy versions 4049 and 4050.

The preceding train window has released-strict reward 0.4302 and
executable-strict success 0.4169, for 96.91% precision among 5,506 released
passes. The sole pure-extra-node case incorrectly derives an irrelevant Taylor
Movie Festival count from the wrong operands, so all 170 executable rejections
are genuine defects. Prompt 567 contributes 100 of them by double-counting the
queried Oakridge Riverside wolf in the Beverly Forest total, producing
`12*x + 15` instead of `11*x + 15` while forcing the gold solution `x = 4`.
Issue-code counts are 139 `solver_equation_mismatch`, 80
`equation_mismatch`, and one each of `expression_syntax` and
`unexpected_node`, with overlap.

There are no logged off-policy cancellation errors in this window and no
errors or truncations in its saved rows. Mismatch KL briefly reaches 0.0105 on
step 4036 but returns to 0.0001 at the checkpoint. Gradient norm stays at most
0.3601 and ends at 0.0767. No NaN, OOM, NCCL, or persistent rollout failure
appears. The step-4050 trainer and orchestrator checkpoints, eight distributed
trainer shards, stable inference weights, 512 training rows, and all 3,000
evaluation rows are complete.

Step 4075 records 26.85% on OP11–20, 13.00% on OP15–20, and 3.40% on
OP21–25. OP20 scores 6.00% on both released and executable strict. Its rolling
last-ten-checkpoint means are 7.20% released and 7.15% executable, compared
with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint. OP21,
OP22, OP23, OP24, and OP25 released strict are 7.5%, 5.5%, 3.5%, 0.5%, and
0.0%, respectively. All executable OP20–25 positives repeat previously solved
problems, so cumulative breadth remains 36, 41, 33, 23, 13, and seven prompts.

Across the full evaluation, 571/3,000 trajectories pass released strict and
557/3,000 pass the executable grader, for 97.55% precision. All three pure
extra-node cases are substantive: OP11 index 58 derives two irrelevant animal
counts from the wrong dependency, OP15 index 188 computes the irrelevant Maple
Creek crow as 3 instead of 2, and OP16 index 50 again computes Mayer Aquarium
deer as 45 instead of 7. The semantic count therefore remains 557, with 14
genuine defects. Issue-code counts are eight `solver_equation_mismatch`, seven
`equation_mismatch`, three `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, three truncations, and every shard
mixes adjacent asynchronous policy versions 4074 and 4075.

The preceding train window has released-strict reward 0.4077 and
executable-strict success 0.3873, for 94.98% precision among 5,219 released
passes. All three pure-extra-node rows incorrectly compute an irrelevant
Jefferson Circus parrot count, so all 262 executable rejections are genuine
defects. Prompt 535 contributes 67 defects through false displayed arithmetic
such as `128 + 8 = 128` while retaining the exact final answer 160. Prompts 570
and 852 contribute another 48 and 47 defects by dropping a term from a
forward-reverse total and then forcing the gold solution. Issue-code counts are
235 `equation_mismatch`, 157 `solver_equation_mismatch`, four
`undefined_symbol`, and three `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.91% and occur at steps 4056,
4073, and 4074, peaking transiently at 22.7%; none survives into saved rows,
which have no errors or truncations. Mismatch KL stays at most 0.0022 and ends
at 0.0001. Gradient norm stays at most 0.1935 and ends at 0.0322. No NaN, OOM,
NCCL, or persistent rollout failure appears. The step-4075 trainer and
orchestrator checkpoints, eight distributed trainer shards, stable inference
weights, 512 training rows, and all 3,000 evaluation rows are complete.

Step 4100 falls to 25.00% on OP11–20 while OP15–20 is 13.58% and OP21–25
returns to 4.00%. OP20 released strict is 6.50% and executable strict is
6.00%. Its rolling last-ten-checkpoint means are 6.95% released and 6.85%
executable, compared with 4.734% pass@1 for the matched strict-filter OP20 SFT
checkpoint. OP21, OP22, OP23, OP24, and OP25 released strict are 8.5%, 6.5%,
3.5%, 1.0%, and 0.5%, respectively. The executable OP25 trajectory repeats
known index 72, and no new executable OP20–25 problem appears, so cumulative
breadth remains 36, 41, 33, 23, 13, and seven prompts.

Across the full evaluation, 540/3,000 trajectories pass released strict and
524/3,000 pass the executable grader, for 97.04% precision. The only pure
extra-node case is the recurring OP16 index 50 trajectory that computes Mayer
Aquarium deer as 45 instead of 7, so all 16 disagreements are genuine defects.
Issue-code counts are 13 `solver_equation_mismatch`, eight
`equation_mismatch`, three `undefined_symbol`, and one `unexpected_node`, with
overlap. Evaluation has no rollout errors, two truncations, and every shard
mixes asynchronous policy versions 4099, 4100, and 4101.

The preceding train window has released-strict reward 0.4805 and
executable-strict success 0.4582, for 95.35% precision among
6,151 released passes. Twelve pure-extra-node rows derive an irrelevant Pine
Ridge subgraph from the wrong dependencies; the two remaining rows carrying
`unexpected_node` also have other substantive errors. All 286 executable
rejections are therefore genuine defects. Prompt 599 contributes 100 defects
by omitting the queried Mayer Aquarium crow from the total, producing
`17*x + 4` instead of `18*x + 4` while forcing `x = 4`. Prompts 263 and 235
contribute another 59 and 32 defects through false equality chains and forced
gold solutions. Issue-code counts are 213 `solver_equation_mismatch`, 180
`equation_mismatch`, 14 `unexpected_node`, and one each of
`undefined_symbol` and `unsupported_expression`, with overlap.

Logged off-policy cancellation errors average 1.62% and occur at steps 4080,
4097, and 4098, peaking transiently at 18.4%; none survives into saved rows,
which have no errors or truncations. Mismatch KL stays at most 0.0012 and ends
at 0.0001. Gradient norm briefly reaches 0.4805 on step 4078 and ends at
0.0248 without subsequent instability. No NaN, OOM, NCCL, or persistent
rollout failure appears. The step-4100 trainer and orchestrator checkpoints,
eight distributed trainer shards, stable inference weights, 512 training rows,
and all 3,000 evaluation rows are complete.

Step 4125 rebounds to 26.15% on OP11–20 and 13.75% on OP15–20, while
OP21–25 is 3.70%. OP20 scores 6.50% on both released and executable strict.
Its rolling last-ten-checkpoint means are 6.85% released and 6.75% executable,
compared with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint.
OP21, OP22, OP23, OP24, and OP25 score 8.0%, 5.0%, 4.0%, 1.0%, and 0.5%,
respectively. OP20 index 49 and OP21 index 166 are new executable successes.
Manual inspection confirms coherent dependency chains ending at exact answers
114 and 82. Cumulative executable OP20–25 breadth therefore reaches 37, 42,
33, 23, 13, and seven prompts.

Across the full evaluation, 560/3,000 trajectories pass released strict and
543/3,000 pass the raw executable grader, for 96.96% raw precision. Three
pure-extra-node disagreements are semantically correct: OP12 index 171 derives
the irrelevant Riverton City private-middle-school count as 12, OP13 index 15
derives the irrelevant Oakridge Riverside bear count as 13, and OP13 index 54
derives the irrelevant Festival de Clairmont total as 18. Counting them gives
546 semantically valid trajectories, 97.50% semantic precision, and 14 genuine
defects. The four other pure-extra-node rows contain substantive errors.
Issue-code counts are eight `solver_equation_mismatch`, seven
`unexpected_node`, six `equation_mismatch`, and one `unsupported_expression`,
with overlap.
Evaluation has no rollout errors, one truncation, and every shard mixes adjacent
asynchronous policy versions 4124 and 4125.

The preceding train window has released-strict reward 0.4213 and raw
executable-strict success 0.4133, for 98.11% raw precision among 5,392 released
passes. Manual inspection finds that all 41 pure-extra-node rows are correct:
40 compute the irrelevant Hawkesbury public-highschool count as 36, and one
computes the irrelevant Rêves de Belleville total as `4*x`. Counting them gives
5,331 semantically valid trajectories, 98.87% semantic precision, and 61
genuine defects. Prompt 662 contributes 19 genuine defects through false
arithmetic such as `64 + 63 = 148` while forcing the exact answer 4, and prompt
1282 contributes another 17 by writing `20 + 112 = 140` before forcing answer
136. Issue-code counts are 58 `equation_mismatch`, 41 `unexpected_node`, 29
`solver_equation_mismatch`, and three `expression_syntax`, with overlap.

There are no logged off-policy cancellation errors in this window. Saved rows
have no errors and three truncations in 12,800 trajectories. Mismatch KL
briefly reaches 0.0046 on step 4101 and ends at 0.0001. Gradient norm briefly
reaches 0.5264 on step 4122 and ends at 0.0166 without subsequent instability.
No NaN, OOM, NCCL, or persistent rollout failure appears. The step-4125 trainer
and orchestrator checkpoints, eight distributed trainer shards, stable
inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 4150 falls to 24.45% on OP11–20 and 12.83% on OP15–20, while OP21–25
remains 3.70%. OP20 scores 6.00% on both released and executable strict. Its
rolling last-ten-checkpoint means are 6.65% released and 6.55% executable,
compared with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint.
OP21, OP22, OP23, OP24, and OP25 score 5.5%, 7.0%, 4.0%, 1.0%, and 1.0%,
respectively. The two OP25 successes repeat known prompts, and no new
executable OP20–25 problem appears, so cumulative breadth remains 37, 42, 33,
23, 13, and seven prompts.

Across the full evaluation, 526/3,000 trajectories pass released strict and
511/3,000 pass the raw executable grader, for 97.15% raw precision. Two
pure-extra-node rows are semantically correct: OP11 index 152 computes the
irrelevant Bundle Ranch crow count as 6, and OP12 index 30 computes the
irrelevant Golden Banana calm-road count as 12. Counting them gives 513
semantically valid trajectories, 97.53% semantic precision, and 13 genuine
defects. The other three pure-extra-node rows contain substantive errors.
Issue-code counts are nine `solver_equation_mismatch`, five `unexpected_node`,
two `equation_mismatch`, and one `undefined_symbol`, with overlap. Evaluation
has no rollout errors, four truncations, and every shard mixes adjacent
asynchronous policy versions 4149 and 4150.

The preceding train window has released-strict reward 0.3525 and raw
executable-strict success 0.3238, for 91.84% raw precision among 4,512 released
passes. Only one of 181 pure-extra-node rows is semantically correct: it
computes the irrelevant Brightford private-middle-school count as 7. Counting
it gives 4,145 semantically valid trajectories, 91.87% semantic precision, and
367 genuine defects. The dip is highly clustered. Prompt 1082 contributes 103
defects by setting Evervale City's culinarian count from Brightford's total
rather than Westhaven City's total, and prompt 1539 contributes 77 by deriving
the Cedar Valley crow count from the wrong Beverly Forest component. Prompt
515 contributes another 64 through a duplicated Ruby Bay category and forced
gold solution. Issue-code counts are 181 `unexpected_node`, 159
`solver_equation_mismatch`, and 155 `equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 1.63% and occur at steps 4133
and 4136, peaking transiently at 23.0%; none survives into saved rows, which
have no errors or truncations. Mismatch KL briefly reaches 0.0073 on step 4143
and ends at 0.0001. Gradient norm reaches 0.3640 at the checkpoint but returns
to 0.0383 on step 4151, with no subsequent instability. No NaN, OOM, NCCL, or
persistent rollout failure appears. The step-4150 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 4175 records 24.55% on OP11–20, 13.42% on OP15–20, and 3.70% on
OP21–25. OP20 scores 6.50% on both released and executable strict. Its rolling
last-ten-checkpoint means are 6.70% released and 6.60% executable, compared
with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint. OP21,
OP22, OP23, OP24, and OP25 score 7.0%, 6.0%, 3.5%, 1.5%, and 0.5%,
respectively. OP21 index 176 is a new executable success; manual inspection
confirms a coherent chain through Beverly Forest and Oakridge Riverside to the
exact answer 2. Cumulative executable OP20–25 breadth is therefore 37, 43, 33,
23, 13, and seven prompts.

Across the full evaluation, 528/3,000 trajectories pass released strict and
515/3,000 pass the raw executable grader, for 97.54% raw precision. OP12 index
30 correctly computes the irrelevant Golden Banana calm-road count as 12;
counting it gives 516 semantically valid trajectories, 97.73% semantic
precision, and 12 genuine defects. The other two pure-extra-node rows contain
substantive errors. Issue-code counts are nine `solver_equation_mismatch`, four
`equation_mismatch`, three `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, two truncations, and every shard
mixes adjacent asynchronous policy versions 4174 and 4175.

The preceding train window has released-strict reward 0.3786 and
executable-strict success 0.3584, for 94.66% precision among 4,846 released
passes. There are no pure-extra-node cases, so all 259 executable rejections
are genuine defects. This partially recovers from step 4150's 91.87% semantic
precision, and the remaining errors are again highly clustered. Prompt 511
contributes 118 defects by writing `9*x + 3 + 30*x + 9 = 33*x + 24` instead of
`39*x + 12` while forcing `x = 1`. Prompts 1304 and 1219 contribute another 42
and 33 defects through false equality chains with correct final answers.
Issue-code counts are 259 `equation_mismatch`, 155
`solver_equation_mismatch`, and one `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 0.98% and occur only at steps
4160 and 4161, peaking transiently at 17.8%; none survives into saved rows,
which have no errors and one truncation. Mismatch KL stays at most 0.0023 and
ends at 0.0002. Gradient norm briefly reaches 0.5721 on step 4159 and ends at
0.0404 without subsequent instability. No NaN, OOM, NCCL, or persistent
rollout failure appears. The step-4175 trainer and orchestrator checkpoints,
eight distributed trainer shards, stable inference weights, 512 training rows,
and all 3,000 evaluation rows are complete.

Step 4200 rebounds to 26.60% on OP11–20 and 14.33% on OP15–20, while
OP21–25 reaches 3.90%. OP20 released strict is 7.50% and executable strict is
7.00%. Its rolling last-ten-checkpoint means remain 6.70% released and 6.60%
executable, compared with 4.734% pass@1 for the matched strict-filter OP20 SFT
checkpoint. OP21, OP22, OP23, OP24, and OP25 score 8.0%, 6.5%, 3.5%, 1.0%,
and 0.5%, respectively. All executable OP20–25 positives repeat previously
solved problems, so cumulative breadth remains 37, 43, 33, 23, 13, and seven
prompts.

Across the full evaluation, 571/3,000 trajectories pass released strict and
555/3,000 pass the raw executable grader, for 97.20% raw precision. Two
pure-extra-node rows are semantically correct: OP11 index 152 computes the
irrelevant Bundle Ranch crow count as 6, and OP12 index 30 computes the
irrelevant Golden Banana calm-road count as 12. OP13 index 74 is not benign:
among its extra nodes it assigns Evervale City's private-middle-school count
as 5 although the prompt specifies 3. Counting only the two valid rows gives
557 semantically valid trajectories, 97.55% semantic precision, and 14 genuine
defects. Issue-code counts are ten `solver_equation_mismatch`, seven
`equation_mismatch`, five `unexpected_node`, and one each of
`definition_dependency_mismatch` and `definition_value_mismatch`, with
overlap. Evaluation has no rollout errors, two truncations, and every shard
mixes adjacent asynchronous policy versions 4199 and 4200.

The preceding train window sets a new 25-step released-strict reward high of
0.5003 and has raw executable-strict success 0.4780, for 95.55% raw precision
among 6,404 released passes. Manual inspection finds 123 executable-grader
false rejects: 122 correctly derive the irrelevant Mayer Aquarium crow count
as 20, and one correctly derives the irrelevant Festival de Saint-Rivage total
as 7. Counting them gives 6,242 semantically valid trajectories, 97.47%
semantic precision, and 162 genuine defects. Prompt 277 contributes 92 genuine
defects by deriving the irrelevant Clearwater Bay regional-medical-school
count from the wrong Shoreline component. The remaining defects are much less
concentrated. Issue-code counts are 216 `unexpected_node`, 68
`equation_mismatch`, 53 `solver_equation_mismatch`, and one `undefined_symbol`,
with overlap.

Logged off-policy cancellation errors average 1.59% and occur at steps 4180,
4181, 4198, and 4199, peaking transiently at 21.1%; none survives into saved
rows, which have no errors or truncations. Mismatch KL briefly reaches 0.0166
on step 4176 and ends at 0.0006. Gradient norm stays at most 0.4399 and ends at
0.1242. No NaN, OOM, NCCL, or persistent rollout failure appears. The
step-4200 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4225 records 25.00% on OP11–20, 13.00% on OP15–20, and 3.60% on
OP21–25. OP20 scores 5.00% on both released and executable strict. Its rolling
last-ten-checkpoint means are 6.50% released and 6.40% executable, compared
with 4.734% pass@1 for the matched strict-filter OP20 SFT checkpoint. OP21,
OP22, OP23, OP24, and OP25 score 6.5%, 5.0%, 5.0%, 1.0%, and 0.5%,
respectively. All executable OP20–25 positives repeat previously solved
problems, so cumulative breadth remains 37, 43, 33, 23, 13, and seven prompts.

Across the full evaluation, 536/3,000 trajectories pass released strict and
520/3,000 pass the raw executable grader, for 97.01% raw precision. Two
pure-extra-node rows are semantically correct: OP11 index 152 computes the
irrelevant Bundle Ranch crow count as 6, and OP12 index 30 computes the
irrelevant Golden Banana calm-road count as 12. Counting them gives 522
semantically valid trajectories, 97.39% semantic precision, and 14 genuine
defects. The other two pure-extra-node rows are substantive: OP15 index 117
invents an unsupported Ruby Bay elementary-school count, and OP16 index 50
again computes Mayer Aquarium deer as 45 instead of 7. Issue-code counts are
ten `solver_equation_mismatch`, four `unexpected_node`, and three
`equation_mismatch`, with overlap. Evaluation has no rollout errors, two
truncations, and every shard mixes adjacent asynchronous policy versions 4224
and 4225.

The preceding train window has released-strict reward 0.4109 and raw
executable-strict success 0.4048, for 98.52% raw precision among 5,259 released
passes. Its sole pure-extra-node row correctly derives the irrelevant
Hawkesbury public-highschool count as `3*x`; counting it gives 5,182
semantically valid trajectories, 98.54% semantic precision, and 77 genuine
defects. This confirms that the step-4150 precision dip was transient prompt
composition. Prompt 1126 contributes 36 genuine defects by writing
`7*x + 10*x + 4 = 21*x + 4` while forcing the gold solution 4, and prompt 1553
contributes another 19 through false numerical equality chains ending at the
correct answer 99. Issue-code counts are 72 `equation_mismatch`, 40
`solver_equation_mismatch`, and one `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.57% and occur only at steps
4219 and 4220, peaking transiently at 20.7%; none survives into saved rows,
which have no errors and one truncation. Mismatch KL stays at most 0.0016 and
ends at 0.0001. Gradient norm briefly reaches 1.1565 on step 4219 but returns
to 0.0364 at the checkpoint without subsequent instability. No NaN, OOM,
NCCL, or persistent rollout failure appears. The step-4225 trainer and
orchestrator checkpoints, eight distributed trainer shards, stable inference
weights, 512 training rows, and all 3,000 evaluation rows are complete.

Step 4250 rebounds to 25.85% on OP11–20 and 13.75% on OP15–20, while
OP21–25 remains 3.60%. OP20 scores 7.50% on both released and executable
strict. Its rolling last-ten-checkpoint means remain 6.50% released and 6.40%
executable, compared with 4.734% pass@1 for the matched strict-filter OP20 SFT
checkpoint. OP21, OP22, OP23, OP24, and OP25 score 6.0%, 7.0%, 3.5%, 1.0%,
and 0.5%, respectively. All executable OP20–25 positives repeat previously
solved problems, so cumulative breadth remains 37, 43, 33, 23, 13, and seven
prompts.

Across the full evaluation, 553/3,000 trajectories pass released strict and
545/3,000 pass the raw executable grader, for 98.55% raw precision. OP11 index
152 correctly computes the irrelevant Bundle Ranch crow count as 6; counting
it gives 546 semantically valid trajectories, 98.73% semantic precision, and
seven genuine defects. The only other pure-extra-node row is the recurring
invalid OP16 index 50 Mayer Aquarium deer computation. Issue-code counts are
four `equation_mismatch`, three `solver_equation_mismatch`, and two
`unexpected_node`, with overlap. Evaluation has no rollout errors, two
truncations, and every shard mixes adjacent asynchronous policy versions 4249
and 4250.

The preceding train window has released-strict reward 0.3674 and
executable-strict success 0.3645, for 99.21% precision among 4,703 released
passes. All 11 pure-extra-node rows are substantive: they set Pine Ridge's bear
count from Cedar Valley's wolf rather than Beverly Forest's wolf, and then
propagate that error into another irrelevant node. All 37 executable rejections
are therefore genuine defects. Issue-code counts are 24 `equation_mismatch`,
ten `solver_equation_mismatch`, 11 `unexpected_node`, and one
`expression_syntax`, with overlap.

Logged off-policy cancellation errors average 2.72% and occur at steps 4228,
4245, and 4248, peaking transiently at 31.6%; none survives into saved rows,
which have no errors and three truncations. Mismatch KL stays at most 0.0068
and ends at 0.0002. Gradient norm briefly reaches 0.8180 on step 4245 and ends
at 0.0639 without subsequent instability. No NaN, OOM, NCCL, or persistent
rollout failure appears. The step-4250 trainer and orchestrator checkpoints,
eight distributed trainer shards, stable inference weights, 512 training rows,
and all 3,000 evaluation rows are complete.

Step 4275 records 25.40% on OP11–20, 13.25% on OP15–20, and 3.60% on
OP21–25. OP20 scores 6.00% released strict and 5.50% executable strict. Its
rolling last-ten-checkpoint means are 6.40% released and 6.25% executable,
respectively 1.666 and 1.516 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
6.5%, 7.0%, 4.0%, 0.0%, and 0.5% released strict, respectively. All
executable OP20–25 positives repeat previously solved problems, so cumulative
breadth remains 37, 43, 33, 23, 13, and seven prompts.

Across the full evaluation, 544/3,000 trajectories pass released strict and
535/3,000 pass the raw executable grader, for 98.35% raw precision. OP12 index
30 correctly computes the irrelevant Golden Banana calm-road count as 12;
counting it gives 536 semantically valid trajectories, 98.53% semantic
precision, and eight genuine defects. The other pure-extra-node rows are
substantive: OP14 index 55 substitutes Ruby Theater's total for the unknown
Shoreline Theater total, and OP16 index 50 again computes Mayer Aquarium deer
as 45 instead of 7. Issue-code counts are five `solver_equation_mismatch`,
four `equation_mismatch`, and three `unexpected_node`, with overlap.
Evaluation has no rollout errors, two truncations, and every shard mixes
adjacent asynchronous policy versions 4274 and 4275.

The preceding train window has released-strict reward 0.3234 and raw
executable-strict success 0.3159, for 97.66% precision among 4,140 released
passes. All 97 executable rejections are genuine defects. Prompt 215
contributes 21 by deriving `C = 2 - 4 = -2` and then replacing it with
`2 * C = 2 * 2 = 4` to force the gold answer 32. Prompt 732 contributes 19 by
using `2*x + 23` where the correct total is `3*x + 35`, and prompt 301
contributes 14 through a false displayed equality chain despite reaching the
gold answer. Issue-code counts are 61 `equation_mismatch`, 44
`solver_equation_mismatch`, and 11 `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 0.94% and occur only at step
4265, peaking transiently at 23.6%; none survives into the 12,800 saved rows,
which have no errors and one truncation. Mismatch KL reaches 0.0121 at step
4260 and ends at 0.0001. Gradient norm stays at most 0.2800 and ends at that
value. No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-4275 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4300 records 24.70% on OP11–20, 13.92% on OP15–20, and 3.50% on
OP21–25. OP20 scores 8.00% on both released and executable strict. Its rolling
last-ten-checkpoint means rise to 6.55% released and 6.40% executable,
respectively 1.816 and 1.666 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
6.5%, 6.5%, 2.5%, 0.5%, and 1.5%, respectively. OP20 index 33 is a new
executable success: it derives Evervale City's total as 4, Glenfield City's
total as 30, and Brightford's exact answer as 61. Cumulative executable
OP20–25 breadth therefore reaches 38, 43, 33, 23, 13, and seven prompts.

Across the full evaluation, 529/3,000 trajectories pass released strict and
514/3,000 pass the raw executable grader, for 97.16% raw precision. OP12 index
30 again adds the correct but irrelevant Golden Banana calm-road value 12;
counting it gives 515 semantically valid trajectories, 97.35% semantic
precision, and 14 genuine defects. The other pure-extra-node rows are the
recurring substantive OP14 index 55 and OP16 index 50 errors. Issue-code counts
are nine `equation_mismatch`, seven `solver_equation_mismatch`, and three
`unexpected_node`, with overlap. Evaluation has no rollout errors, two
truncations, and every shard mixes adjacent asynchronous policy versions 4299
and 4300.

The preceding train window has released-strict reward 0.3710 and raw
executable-strict success 0.3543, for 95.49% raw precision among 4,749 released
passes. Prompt 154 accounts for all 34 pure-extra-node rejections: 29 correctly
derive the irrelevant Oakridge Riverside bear count as 24, while five use the
wrong dependency and obtain 12. Counting only the 29 valid rows gives 4,564
semantically valid trajectories, 96.10% semantic precision, and 185 genuine
defects. Prompt 62 contributes 118 defects by replacing `12 - 3*x` with `12`
inside the total, producing the false equation `2*x + 20 = 17` before forcing
the gold answer 3. Prompt 1184 contributes 30 through a correct initial
equation `44*x + 2 = 90` followed by the false transformations `44*x = 160`
and `x = 160 / 44` before also forcing the gold answer 2. Issue-code counts,
after removing the 29 benign extras, are 164 `solver_equation_mismatch`, 142
`equation_mismatch`, five `unexpected_node`, and one `expression_syntax`, with
overlap.

Logged rollout errors are zero throughout steps 4276–4300; the two saved-row
truncations occur at steps 4290 and 4293. Mismatch KL stays at most 0.0014 and
ends at 0.0003. Gradient norm stays at most 0.3047 and ends at 0.2184. No NaN,
OOM, NCCL failure, or persistent rollout failure appears. The step-4300
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 4325 records 23.50% on OP11–20, 12.58% on OP15–20, and 3.40% on
OP21–25. OP20 scores 5.50% on both released and executable strict. Its rolling
last-ten-checkpoint means are 6.50% released and 6.35% executable,
respectively 1.766 and 1.616 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
9.0%, 5.0%, 3.0%, 0.0%, and 0.0%, respectively. OP23 index 143 is a new
executable success: it derives Pine Ridge's total as 8, Beverly Forest's total
as 36, and Maple Creek's exact answer as 33. Cumulative executable OP20–25
breadth therefore reaches 38, 43, 33, 24, 13, and seven prompts.

Across the full evaluation, 504/3,000 trajectories pass released strict and
488/3,000 pass the executable grader, for 96.83% precision. All 16 rejections
are genuine defects. The only pure-extra-node row is recurring OP16 index 50,
which derives Mayer Aquarium deer as 45 instead of the prompt-consistent 7.
Issue-code counts are 15 `solver_equation_mismatch`, eight
`equation_mismatch`, two `undefined_symbol`, and one `unexpected_node`, with
overlap. Evaluation has no rollout errors, three truncations, and every shard
mixes adjacent asynchronous policy versions 4324 and 4325.

The preceding train window has released-strict reward 0.3494 and
executable-strict success 0.3223, for 92.26% precision among 4,472 released
passes. All 346 rejections are genuine defects. Prompt 383 contributes 113 by
using the false total equation `19*x + 32 = 64`, then transforming it to
`19*x = 28` before forcing the gold answer 4. Prompt 1082 contributes 111 by
setting the irrelevant Evervale City culinarian-school count to Brightford's
total 5 even though the prompt equates it to Westhaven City's total 21. Prompt
1168 contributes 68 by starting from `19*x + 14 = 54`, transforming it to the
false `19*x = 46`, and forcing the gold answer 2. Prompt 1353 contributes 33
through false displayed totals `24 + 64 = 160` and `160 + 40 = 128`.
Issue-code counts are 184 `solver_equation_mismatch`, 111 `unexpected_node`,
58 `equation_mismatch`, one `undefined_symbol`, and one `expression_syntax`,
with overlap.

Logged off-policy cancellation errors average 1.64% and occur at steps 4308,
4309, and 4311, peaking transiently at 17.0%; none survives into the 12,800
saved rows, which have no truncations. Mismatch KL stays at most 0.0015 and
ends at 0.0001. Gradient norm stays at most 0.1878 and ends at 0.1154. No NaN,
OOM, NCCL failure, or persistent rollout failure appears. The step-4325
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 4350 rebounds to 24.90% on OP11–20 and 13.58% on OP15–20, while
OP21–25 remains 3.40%. OP20 scores 7.50% on both released and executable
strict. Its rolling last-ten-checkpoint means rise to 6.60% released and 6.45%
executable, respectively 1.866 and 1.716 percentage points above the matched
strict-filter OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and
OP25 score 6.0%, 4.0%, 5.0%, 1.5%, and 0.5%, respectively. All executable
OP20–25 positives repeat previously solved problems, so cumulative breadth
remains 38, 43, 33, 24, 13, and seven prompts.

Across the full evaluation, 532/3,000 trajectories pass released strict and
518/3,000 pass the raw executable grader, for 97.37% raw precision. OP11 index
152 correctly derives the irrelevant Bundle Ranch crow count as 6; counting
it gives 519 semantically valid trajectories, 97.56% semantic precision, and
13 genuine defects. The other four pure-extra-node rows are substantive:
OP11 index 16 derives Jefferson Circus deer from the wrong dependencies, OP14
index 55 repeats the invalid Shoreline City computation, OP15 index 117
invents an unsupported Ruby Bay value, and OP16 index 50 repeats the invalid
Mayer Aquarium deer computation. After the semantic adjustment, issue-code
counts are seven `solver_equation_mismatch`, four `unexpected_node`, and three
`equation_mismatch`, with overlap. Evaluation has no rollout errors, two
truncations, and every shard mixes adjacent asynchronous policy versions 4349
and 4350.

The preceding train window has released-strict reward 0.4310 and raw
executable-strict success 0.4222, for 97.95% raw precision among 5,517 released
passes. All six pure-extra-node rejections are semantically valid. Five prompt
259 rows correctly derive the irrelevant Saint-Rivage total as 4, with one
also correctly deriving the downstream Rêves de Belleville value 12; prompt
1559 correctly derives South Zoo deer as 4. Counting them gives 5,410
semantically valid trajectories, 98.06% semantic precision, and 107 genuine
defects. Prompt 515 contributes 68 by writing `22*x + 18*x = 44*x` instead of
`40*x`, then forcing the gold answer 3. Prompt 565 contributes 17 through the
false totals `66 + 5 = 83` and `83 + 13 = 84`. After removing the six benign
extras, issue-code counts are 91 `equation_mismatch` and 73
`solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 0.71% and occur only at step
4337, peaking transiently at 17.7%; none survives into the 12,800 saved rows,
which contain one truncation at step 4330. Mismatch KL stays at most 0.0004 and
ends at zero. Gradient norm stays at most 0.1735 and ends at 0.0264. No NaN,
OOM, NCCL failure, or persistent rollout failure appears. The step-4350
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 4375 reaches 25.25% on OP11–20 and holds 13.58% on OP15–20, while
OP21–25 rises to 4.30%. OP20 scores 6.50% on both released and executable
strict. Its rolling last-ten-checkpoint means remain 6.60% released and 6.45%
executable, respectively 1.866 and 1.716 percentage points above the matched
strict-filter OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and
OP25 score 6.5%, 8.0%, 4.0%, 2.0%, and 1.0% released strict, respectively.
All executable OP20–25 positives repeat previously solved problems, so
cumulative breadth remains 38, 43, 33, 24, 13, and seven prompts.

Across the full evaluation, 548/3,000 trajectories pass released strict and
533/3,000 pass the raw executable grader, for 97.26% raw precision. OP12 index
30 correctly derives the irrelevant Golden Banana calm-road value 12;
counting it gives 534 semantically valid trajectories, 97.45% semantic
precision, and 14 genuine defects. The other two pure-extra-node rows are the
recurring substantive OP14 index 55 and OP16 index 50 errors. After the
semantic adjustment, issue-code counts are seven `equation_mismatch`, six
`solver_equation_mismatch`, two `undefined_symbol`, and two `unexpected_node`,
with overlap. Evaluation has no rollout errors, one truncation, and every shard
mixes adjacent asynchronous policy versions 4374 and 4375.

The preceding train window has released-strict reward 0.4200 and
executable-strict success 0.4061, for 96.69% precision among 5,376 released
passes. All 178 rejections are genuine defects. Prompt 62 contributes 122 by
dropping the `-3*x` term from `12 - 3*x`, creating the false total
`2*x + 20 = 17`, and then forcing the gold answer 3. Prompt 1178 contributes
16 through two false coefficient reductions in the Maple Creek total before
forcing the gold answer 1. Prompt 1323 contributes 11 by writing
`30*x + 12 + 9*x + 4 = 33*x + 16` and then forcing the gold answer 1.
Issue-code counts are 170 `equation_mismatch`, 157
`solver_equation_mismatch`, and one `expression_syntax`, with overlap.

Logged off-policy cancellation errors average 1.20% and occur only at step
4368, peaking transiently at 30.0%; none survives into the 12,800 saved rows,
which contain one truncation at step 4363. Mismatch KL stays at most 0.0005 and
ends at 0.0001. Gradient norm reaches 0.3086 at step 4373 and ends at 0.0221
without instability. No NaN, OOM, NCCL failure, or persistent rollout failure
appears. The step-4375 trainer and orchestrator checkpoints, eight distributed
trainer shards, stable inference weights, 512 training rows, and all 3,000
evaluation rows are complete.

Step 4400 holds 25.25% on OP11–20, raises OP15–20 to 14.33%, and records
3.50% on OP21–25. OP20 scores 8.50% on both released and executable strict.
Its rolling last-ten-checkpoint means rise to 6.85% released and 6.70%
executable, respectively 2.116 and 1.966 percentage points above the matched
strict-filter OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and
OP25 score 8.0%, 6.0%, 3.0%, 0.5%, and 0.0%, respectively. OP20 index 20 is a
new executable success: it derives Cedar Valley's total as 2, Pine Ridge's
total as 20, Maple Creek's total as 32, and Beverly Forest's exact answer as
72. Cumulative executable OP20–25 breadth therefore reaches 39, 43, 33, 24,
13, and seven prompts.

Across the full evaluation, 540/3,000 trajectories pass released strict and
526/3,000 pass the raw executable grader, for 97.41% raw precision. OP12 index
30 correctly derives the irrelevant Golden Banana calm-road value 12;
counting it gives 527 semantically valid trajectories, 97.59% semantic
precision, and 13 genuine defects. The other two pure-extra-node rows are the
recurring substantive OP14 index 55 and OP16 index 50 errors. After the
semantic adjustment, issue-code counts are nine `solver_equation_mismatch`,
five `equation_mismatch`, and two `unexpected_node`, with overlap. Evaluation
has no rollout errors, one truncation, and every shard mixes adjacent
asynchronous policy versions 4399 and 4400.

The preceding train window has released-strict reward 0.4479 and raw
executable-strict success 0.4416, for 98.60% raw precision among 5,733 released
passes. One prompt 823 row correctly derives the irrelevant Clairmont
detective-thriller count as 4; counting it gives 5,654 semantically valid
trajectories, 98.62% semantic precision, and 79 genuine defects. Prompt 705
contributes 29 by replacing `39*x + 24` with `45*x + 24` and then replacing
the resulting `46*x + 25` with `40*x + 41`, before forcing the gold answer 2.
Prompt 751 contributes 16 invalid extra nodes: 12 derive Pine Ridge bear as 3
instead of 2, and four derive Beverly Forest bear as 6 instead of 5. Prompt
156 contributes nine by deriving Jefferson Circus parrot as 4 instead of 5.
After the semantic adjustment, issue-code counts are 52 `equation_mismatch`,
40 `solver_equation_mismatch`, 25 `unexpected_node`, and two
`undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.41% and occur at steps 4386
and 4400, peaking transiently at 34.2%; none survives into the 12,800 saved
rows, which have no truncations. Mismatch KL stays at most 0.0008 and ends at
0.0001. Gradient norm stays at most 0.2713 and ends at 0.0779. No NaN, OOM,
NCCL failure, or persistent rollout failure appears. The step-4400 trainer and
orchestrator checkpoints, eight distributed trainer shards, stable inference
weights, 512 training rows, and all 3,000 evaluation rows are complete.

Step 4425 reaches 25.60% on OP11–20, 14.17% on OP15–20, and 4.20% on
OP21–25. OP20 scores 6.50% on both released and executable strict. Its rolling
last-ten-checkpoint means remain 6.85% released and 6.70% executable,
respectively 2.116 and 1.966 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
8.0%, 8.5%, 3.5%, 0.5%, and 0.5%, respectively. All executable OP20–25
positives repeat previously solved problems, so cumulative breadth remains 39,
43, 33, 24, 13, and seven prompts.

Across the full evaluation, 554/3,000 trajectories pass released strict and
539/3,000 pass the raw executable grader, for 97.29% raw precision. OP12 index
30 correctly derives the irrelevant Golden Banana calm-road value 12, and
OP15 index 44 correctly derives the irrelevant Northwood total as 10. Counting
both gives 541 semantically valid trajectories, 97.65% semantic precision, and
13 genuine defects. The other two pure-extra-node rows are the recurring
substantive OP14 index 55 and OP16 index 50 errors. After the semantic
adjustment, issue-code counts are seven `solver_equation_mismatch`, six
`equation_mismatch`, two `undefined_symbol`, and two `unexpected_node`, with
overlap. Evaluation has no rollout errors, one truncation, and every shard
mixes adjacent asynchronous policy versions 4424 and 4425.

The preceding train window has released-strict reward 0.3462 and raw
executable-strict success 0.3334, for 96.30% raw precision among 4,431 released
passes. Three prompt 380 rows correctly derive the irrelevant Jefferson Circus
eagle count as 3; a fourth row invents an unsupported Mayer Aquarium eagle
count of 4. Counting only the valid rows gives 4,270 semantically valid
trajectories, 96.37% semantic precision, and 161 genuine defects. Prompt 574
contributes 56 by replacing `11*x + 21` with `15*x + 21` before forcing the
gold answer 3. Prompt 992 contributes 29 by replacing the constant value 6
with `6*x + 8` inside the Mayer Aquarium total before forcing the gold answer
2. Prompt 1898 contributes 27 through the false Ruby Bay totals
`36 + 44 = 92` and `92 + 4 = 84`. After the semantic adjustment, issue-code
counts are 154 `equation_mismatch`, 112 `solver_equation_mismatch`, and one
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.95% and occur at steps 4403
and 4408, peaking transiently at 18.6%; none survives into the 12,800 saved
rows, which contain two truncations at steps 4405 and 4414. Mismatch KL stays
at most 0.0010 and ends at 0.0001. Gradient norm stays at most 0.1753 and ends
at 0.0271. No NaN, OOM, NCCL failure, or persistent rollout failure appears.
The step-4425 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4450 records 23.90% on OP11–20, 13.75% on OP15–20, and 4.30% on
OP21–25. OP20 scores 8.50% on both released and executable strict. Its rolling
last-ten-checkpoint means rise to 6.95% released and 6.80% executable,
respectively 2.216 and 2.066 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
8.5%, 6.0%, 4.5%, 2.0%, and 0.5%, respectively. All executable OP20–25
positives repeat previously solved problems, so cumulative breadth remains 39,
43, 33, 24, 13, and seven prompts.

Across the full evaluation, 521/3,000 trajectories pass released strict and
511/3,000 pass the raw executable grader, for 98.08% raw precision. OP11 index
68 correctly derives the irrelevant Northwood calm-road value as 7; counting
it gives 512 semantically valid trajectories, 98.27% semantic precision, and
nine genuine defects. The other two pure-extra-node rows are the recurring
substantive OP14 index 55 and OP16 index 50 errors. After the semantic
adjustment, issue-code counts are six `solver_equation_mismatch`, three
`equation_mismatch`, two `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, two truncations, and every shard
mixes adjacent asynchronous policy versions 4449 and 4450.

The preceding train window has released-strict reward 0.4644 and
executable-strict success 0.4511, for 97.14% precision among 5,944 released
passes. All 170 rejections are genuine defects. Prompt 1539 contributes 65 by
deriving the irrelevant Cedar Valley crow count as 23 or 17 instead of the
prompt-consistent 19. Prompt 263 contributes 51 by replacing the constant
`x + 4` with `5*x + 4` inside the Verdi total and then forcing the gold answer
2. Prompt 392 contributes eight by replacing `11*x + 9` with `11*x + 15`
before forcing the gold answer 1. Issue-code counts are 94
`equation_mismatch`, 83 `solver_equation_mismatch`, 71 `unexpected_node`, and
one `expression_syntax`, with overlap.

Logged off-policy cancellation errors average 1.28% and occur only at step
4431, peaking transiently at 32.0%; none survives into the 12,800 saved rows,
which contain one truncation at step 4441. Mismatch KL stays at most 0.0003 and
ends at 0.0001. Gradient norm stays at most 0.2344 and ends at 0.1133. No NaN,
OOM, NCCL failure, or persistent rollout failure appears. The step-4450
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 4475 reaches 25.20% on OP11–20, 13.33% on OP15–20, and 4.00% on
OP21–25. OP20 scores 5.50% on both released and executable strict. Its rolling
last-ten-checkpoint means rise to 7.00% released and 6.85% executable,
respectively 2.266 and 2.116 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
6.0%, 8.0%, 4.5%, 1.0%, and 0.5%, respectively. All executable OP20–25
positives repeat previously solved problems, so cumulative breadth remains 39,
43, 33, 24, 13, and seven prompts.

Across the full evaluation, 544/3,000 trajectories pass released strict and
536/3,000 pass the executable grader, for 98.53% precision. All eight
rejections are genuine defects. The only pure-extra-node rows are the
recurring substantive OP14 index 55 and OP16 index 50 errors. Issue-code
counts are five `solver_equation_mismatch`, three `equation_mismatch`, two
`unexpected_node`, one `undefined_symbol`, and one `expression_syntax`, with
overlap. Evaluation has no rollout errors, two truncations, and every shard
mixes adjacent asynchronous policy versions 4474 and 4475.

The preceding train window has released-strict reward 0.4325 and raw
executable-strict success 0.4002, for 92.54% raw precision among 5,536 released
passes. Prompt 698 accounts for all 91 pure-extra-node rejections: 88 correctly
derive Hawkesbury private-middle-school count as 6, while three derive the
wrong value 5. Counting only the valid rows gives 5,211 semantically valid
trajectories, 94.13% semantic precision, and 325 genuine defects. Prompt 590
contributes 116 by replacing `23*x + 48` with `23*x + 60` before forcing the
gold answer 3. Prompt 570 contributes 56 by replacing `x + 88` with
`x + 72` before forcing the gold answer 3. Prompt 597 contributes 53 by
replacing the constant deer value 3 with `3*x + 3` inside the Cedar Valley
total before forcing the gold answer 1. After the semantic adjustment,
issue-code counts are 279 `equation_mismatch`, 276
`solver_equation_mismatch`, three `unexpected_node`, and one
`undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.24% and occur at steps 4465
and 4469, peaking transiently at 17.6%; none survives into the 12,800 saved
rows, which contain two truncations at steps 4451 and 4466. Mismatch KL stays
at most 0.0006 and ends at 0.0001. Gradient norm stays at most 0.1292 and ends
at 0.0389. No NaN, OOM, NCCL failure, or persistent rollout failure appears.
The step-4475 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4500 rebounds to 25.85% on OP11–20, records 13.33% on OP15–20, and
reaches 4.20% on OP21–25. OP20 scores 7.00% on both released and executable
strict. Its rolling last-ten-checkpoint means remain 6.95% released and 6.80%
executable, respectively 2.216 and 2.066 percentage points above the matched
strict-filter OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and
OP25 score 6.0%, 8.0%, 4.0%, 1.0%, and 2.0%, respectively. All executable
OP20–25 positives repeat previously solved problems, so cumulative breadth
remains 39, 43, 33, 24, 13, and seven prompts.

Across the full evaluation, 559/3,000 trajectories pass released strict and
553/3,000 pass the raw executable grader, for 98.93% raw precision. OP17 index
172 correctly derives the irrelevant Montreval calm-road value as 5; counting
it gives 554 semantically valid trajectories, 99.11% semantic precision, and
five genuine defects. After the semantic adjustment, issue-code counts are
four `solver_equation_mismatch` and four `equation_mismatch`, with overlap.
Evaluation has no rollout errors or truncations, and every shard mixes adjacent
asynchronous policy versions 4499 and 4500.

The preceding train window has released-strict reward 0.3620 and raw
executable-strict success 0.3501, for 96.72% raw precision among 4,633 released
passes. Its sole pure-extra-node row correctly derives Pine Ridge deer as 3;
counting it gives 4,482 semantically valid trajectories, 96.74% semantic
precision, and 151 genuine defects. Prompt 1219 contributes 58 through the
false totals `16 + 84 = 112` and `112 + 2 = 102`. Prompt 588 contributes 39 by
replacing `15*x + 32` with `21*x + 32` before forcing the gold answer 2.
Prompt 567 contributes 26 by replacing `11*x + 15` with `15*x + 15` before
forcing the gold answer 4. After the semantic adjustment, issue-code counts
are 136 `equation_mismatch` and 87 `solver_equation_mismatch`, with overlap.

Logged rollout errors are zero throughout steps 4476–4500. The 12,800 saved
rows contain six truncations: one at step 4478 and five at step 4499. Mismatch
KL stays at most 0.0004 and ends at zero. Gradient norm stays at most 0.1823
and ends at 0.0447. No NaN, OOM, NCCL failure, or persistent rollout failure
appears. The step-4500 trainer and orchestrator checkpoints, eight distributed
trainer shards, stable inference weights, 512 training rows, and all 3,000
evaluation rows are complete.

Step 4525 records 24.95% on OP11–20, 14.00% on OP15–20, and 3.70% on
OP21–25. OP20 scores 9.00% released strict and 8.50% executable strict. The
rolling last-ten-checkpoint means rise to 7.25% released and 7.10% executable,
respectively 2.516 and 2.366 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
6.5%, 6.5%, 3.5%, 1.5%, and 0.5%, respectively. No new executable OP20–25
problem appears, so cumulative breadth remains 39, 43, 33, 24, 13, and seven
prompts.

Across the full evaluation, 536/3,000 trajectories pass released strict and
524/3,000 pass the raw executable grader, for 97.76% raw precision. OP12 index
171 correctly derives the irrelevant Riverton private-middle-school count as
12. Counting that benign extra-node row gives 525 semantically valid
trajectories, 97.95% semantic precision, and 11 genuine defects. The other two
pure-extra-node rows, OP14 index 55 and OP16 index 50, are recurring invalid
derivations. After the semantic adjustment, issue-code counts are six
`solver_equation_mismatch`, five `equation_mismatch`, two `unexpected_node`,
and one `undefined_symbol`, with overlap. Evaluation has no rollout errors,
four truncations, and mixes adjacent asynchronous policy versions 4524 and
4525.

The preceding train window has released-strict reward 0.3927 and raw
executable-strict success 0.3784, for 96.34% raw precision among 5,027 released
passes. All 38 pure-extra-node rows from prompt 86 correctly derive the
irrelevant Hawkesbury public-high-school count as 36. Counting them gives
4,881 semantically valid trajectories, 97.10% semantic precision, and 146
genuine defects. Prompt 215 contributes 43 defects by deriving `D = 2 - 4 =
-2` and then using `2 * 2 = 4` for `2 * D`. Prompt 1400 contributes 25 through
the false totals `84 + 2 = 62` and `62 + 4 = 90`. Prompt 664 contributes 24 by
claiming that `12*x + 48 = 64` implies `12*x = 12`, then forcing the gold
answer 1. After the semantic adjustment, issue-code counts are 120
`equation_mismatch` and 55 `solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 3.10% and occur at steps 4501,
4518, 4519, and 4522, peaking transiently at 21.7%; none survives into the
12,800 saved rows, which also contain no truncations. Mismatch KL stays at most
0.0008 and ends at 0.0001. Gradient norm stays at most 0.5038 and ends at
0.0605. No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-4525 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4550 records 25.10% on OP11–20, 13.42% on OP15–20, and 3.20% on
OP21–25. OP20 scores 7.00% on both released and executable strict. The rolling
last-ten-checkpoint means are 7.15% released and 7.00% executable,
respectively 2.416 and 2.266 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
5.5%, 4.5%, 4.0%, 1.0%, and 1.0%, respectively. OP22 index 18 and OP23 index
81 are new executable successes. Manual inspection confirms OP22's chain from
the Saint-Rivage total 12 through the Montreval total 38 to exact answer 81,
and OP23's chain from the Clearwater total 3 through the Oakbridge total 19 to
exact answer 42. Cumulative executable OP20–25 breadth therefore becomes 39,
43, 34, 25, 13, and seven prompts.

Across the full evaluation, 534/3,000 trajectories pass released strict and
523/3,000 pass the raw executable grader, for 97.94% raw precision. All three
pure-extra-node rows are benign: OP11 index 152 derives the irrelevant Bundle
Ranch crow count as 6, OP12 index 30 derives the Golden Banana calm-road count
as 12, and OP13 index 54 derives the Clairmont total as 18. Counting them gives
526 semantically valid trajectories, 98.50% semantic precision, and eight
genuine defects. After the semantic adjustment, issue-code counts are eight
`solver_equation_mismatch`, three `equation_mismatch`, and two
`undefined_symbol`, with overlap. Evaluation has no rollout errors, two
truncations, and mixes adjacent asynchronous policy versions 4549 and 4550.

The preceding train window has released-strict reward 0.3878 and raw
executable-strict success 0.3680, for 94.90% executable precision among 4,964
released passes. It has no pure-extra-node-only rejection, leaving 253 genuine
defects. Prompt 580 contributes 78 by changing the correct solver equation
`22*x - 66 = 0` to `22*x - 72 = 0` before forcing answer 3. Prompt 535
contributes 55 through the false totals `128 + 8 = 160` and `160 + 24 = 160`.
Prompt 301 contributes 22 by using the undefined self-reference `i = f + i`,
constructing `2*x + 21` instead of `3*x + 21`, and then claiming that
`x = 12 / 2` equals the gold answer 4. Issue-code counts are 162
`equation_mismatch`, 152 `solver_equation_mismatch`, 21 `undefined_symbol`,
and one each of `unexpected_node` and `definition_dependency_mismatch`, with
overlap.

Logged off-policy cancellation errors average 2.22% and occur at steps 4539,
4541, and 4548, peaking transiently at 20.6%; none survives into the 12,800
saved rows. The saved rows contain two truncations at step 4541. Mismatch KL
stays at most 0.0008 and ends at 0.0001. Gradient norm stays at most 0.6082 and
ends at 0.0727. No NaN, OOM, NCCL failure, or persistent rollout failure
appears. The step-4550 trainer and orchestrator checkpoints, eight distributed
trainer shards, stable inference weights, 512 training rows, and all 3,000
evaluation rows are complete.

Step 4575 records 22.35% on OP11–20 and 12.17% on OP15–20, while OP21–25
rises to 4.20%. OP20 scores 7.50% on both released and executable strict. The
rolling last-ten-checkpoint means rise to 7.35% released and 7.20% executable,
respectively 2.616 and 2.466 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
8.0%, 8.0%, 4.5%, 0.0%, and 0.5%, respectively. OP20 index 4 is a new
executable success. Manual inspection confirms Glenfield's total 2,
Brightford's total 10, and Hawkesbury's exact answer 98. Cumulative executable
OP20–25 breadth therefore becomes 40, 43, 34, 25, 13, and seven prompts.

Across the full evaluation, 489/3,000 trajectories pass released strict and
476/3,000 pass the executable grader, for 97.34% precision. None of the 13
rejections is a pure-extra-node case, so all are genuine defects. Issue-code
counts are nine each of `equation_mismatch` and
`solver_equation_mismatch`, with overlap. Evaluation has no rollout errors,
two truncations, and mixes adjacent asynchronous policy versions 4574 and
4575.

The preceding train window has released-strict reward 0.3916 and
executable-strict success 0.3785, for 96.67% executable precision among 5,012
released passes. Its only pure-extra-node rejection is substantive: prompt
547 should derive the South Zoo bear count as three from its racoon count one,
but instead uses an unrelated value two and reports six. All 167 rejections
are therefore genuine defects. Prompt 1184 contributes 50 by replacing
`44*x + 2` with `43*x + 2` before forcing answer 2. Prompt 235 contributes 34
by claiming that `19*x + 2*x + 4` equals `23*x + 4`, then forcing answer 2.
Prompt 1282 contributes 19 through the false totals `20 + 112 = 140` and
`140 + 4 = 136`. Issue-code counts are 124
`solver_equation_mismatch`, 107 `equation_mismatch`, two
`expression_syntax`, and one `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.73% and occur at steps 4565
and 4568, peaking transiently at 15.9%; none survives into the 12,800 saved
rows. The saved rows contain four truncations at steps 4569 and 4570. Mismatch
KL stays at most 0.0013 and ends at 0.0004. Gradient norm stays at most 0.2002
and ends at 0.0771. No NaN, OOM, NCCL failure, or persistent rollout failure
appears. The step-4575 trainer and orchestrator checkpoints, eight distributed
trainer shards, stable inference weights, 512 training rows, and all 3,000
evaluation rows are complete.

Step 4600 records 23.20% on OP11–20, 12.08% on OP15–20, and 3.60% on
OP21–25. OP20 scores 5.00% on both released and executable strict. The rolling
last-ten-checkpoint means are 7.10% released and 6.95% executable,
respectively 2.366 and 2.216 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
6.5%, 7.0%, 4.0%, 0.0%, and 0.5%, respectively. All executable OP20–25
positives repeat previously solved problems, so cumulative breadth remains 40,
43, 34, 25, 13, and seven prompts.

Across the full evaluation, 500/3,000 trajectories pass released strict and
487/3,000 pass the raw executable grader, for 97.40% raw precision. OP12 index
102 correctly derives the irrelevant Verdi futuristic-sci-fi count as 2. The
other pure-extra-node rows, recurring OP14 index 55 and OP16 index 50, use the
wrong source entities and are invalid. Counting only the benign row gives 488
semantically valid trajectories, 97.60% semantic precision, and 12 genuine
defects. After the semantic adjustment, issue-code counts are eight
`solver_equation_mismatch`, seven `equation_mismatch`, two
`unexpected_node`, and one `undefined_symbol`, with overlap. Evaluation has
no rollout errors or truncations and mixes adjacent asynchronous policy
versions 4599 and 4600.

The preceding train window has released-strict reward 0.4327 and raw
executable-strict success 0.4148, for 95.88% raw precision among 5,538 released
passes. Its sole pure-extra-node row, prompt 103, correctly derives the
irrelevant Hawkesbury public-high-school count as `3*x`; counting it gives
5,311 semantically valid trajectories, 95.90% semantic precision, and 227
genuine defects. Prompt 511 contributes 121 by claiming that
`34*x + 9 + 5*x + 3` equals `39*x + 18`, then forcing answer 1. Prompt 1126
contributes 37 after reusing the entity symbol `z` for an intermediate and
thereby displaying false dependency equalities. Prompt 395 contributes 16 by
claiming that `x + 56 + 12` equals `x + 56`, then forcing answer 3. Issue-code
counts are 224 `equation_mismatch`, 185 `solver_equation_mismatch`, and one
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.00% and occur at steps 4597
and 4598, peaking transiently at 17.7%; none survives into the 12,800 saved
rows. The saved rows contain one truncation at step 4592. Mismatch KL stays at
most 0.0013 and ends at 0.0001. Gradient norm stays at most 0.7974 and ends at
0.0581. No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-4600 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4625 records 24.20% on OP11–20, 12.42% on OP15–20, and 4.00% on
OP21–25. OP20 scores 7.50% on both released and executable strict. The rolling
last-ten-checkpoint means rise to 7.20% released and 7.05% executable,
respectively 2.466 and 2.316 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
8.0%, 6.5%, 3.0%, 1.5%, and 1.0%, respectively. All executable OP20–25
positives repeat previously solved problems, so cumulative breadth remains 40,
43, 34, 25, 13, and seven prompts.

Across the full evaluation, 524/3,000 trajectories pass released strict and
517/3,000 pass the raw executable grader, for 98.66% raw precision. OP12 index
171 correctly derives the irrelevant Riverton private-middle-school count as
12. The other pure-extra-node row, recurring OP16 index 50, uses the South Zoo
bear value in place of the Mayer bear and is invalid. Counting only the benign
row gives 518 semantically valid trajectories, 98.85% semantic precision, and
six genuine defects. After the semantic adjustment, issue-code counts are four
`solver_equation_mismatch`, three `equation_mismatch`, and one
`unexpected_node`, with overlap. Evaluation has no rollout errors, two
truncations, and mixes adjacent asynchronous policy versions 4624 and 4625.

The preceding train window has released-strict reward 0.4008 and
executable-strict success 0.3861, for 96.34% executable precision among 5,130
released passes. It has no pure-extra-node rejection, leaving 188 genuine
defects. Prompt 599 contributes 103 by omitting one `4*x` entity from the
Mayer Aquarium total, replacing `18*x + 4` with `14*x + 4`, and forcing answer
4. Prompt 903 contributes 25 by replacing the correct Ruby Bay total
`9*x + 5` with `5*x + 5` before forcing answer 3. Prompt 662 contributes 15 by
claiming that `x + 64 + 63` equals `x + 148`, then solving the different
equation `x + 64 = 131` to force answer 4. Issue-code counts are 163
`solver_equation_mismatch` and 90 `equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 0.23% and occur only at step
4606, peaking transiently at 5.8%; none survives into the 12,800 saved rows.
The saved rows contain one truncation at step 4618. Mismatch KL spikes to
0.0079 at step 4606, returns to 0.0001 on step 4607, and ends at 0.0004.
Gradient norm reaches 0.9956 at step 4625 but returns to 0.1202 on step 4626.
No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-4625 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4650 falls to 20.95% on OP11–20 and 11.25% on OP15–20, with OP21–25 at
3.30%. OP20 scores 4.50% on both released and executable strict. The rolling
last-ten-checkpoint means are 6.80% released and 6.65% executable,
respectively 2.066 and 1.916 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
6.5%, 4.5%, 4.0%, 1.0%, and 0.5% released strict, respectively. All executable
OP20–25 positives repeat previously solved problems, so cumulative breadth
remains 40, 43, 34, 25, 13, and seven prompts.

Across the full evaluation, 452/3,000 trajectories pass released strict and
437/3,000 pass the raw executable grader, for 96.68% raw precision. OP11 index
152 correctly derives the irrelevant Bundle Ranch crow count as 6, and OP13
index 54 correctly derives the irrelevant Clairmont total as 18. The third
pure-extra-node row, recurring OP16 index 50, uses the wrong source entity and
is invalid. Counting the two benign rows gives 439 semantically valid
trajectories, 97.12% semantic precision, and 13 genuine defects. After the
semantic adjustment, issue-code counts are eight `solver_equation_mismatch`,
four `equation_mismatch`, and one each of `unexpected_node`,
`undefined_symbol`, `definition_dependency_mismatch`, and
`definition_value_mismatch`, with overlap. Evaluation has no rollout errors,
one truncation, and mixes adjacent asynchronous policy versions 4649 and 4650.

The preceding train window has released-strict reward 0.3977 and raw
executable-strict success 0.3635, for 91.41% raw precision among 5,090 released
passes. Prompt 154 accounts for all 123 pure-extra-node rejections. Its extra
Oakridge bear derivation is irrelevant to the requested racoon: 118 rows
correctly derive it as 24 from the Cedar Valley deer, while five use the
Oakridge wolf and incorrectly derive 12. Counting only the valid rows gives
4,771 semantically valid trajectories, 93.73% semantic precision, and 319
genuine defects. Prompt 704 contributes 121 by replacing the correct total
`7*x + 13` with `6*x + 13` before forcing answer 1. Prompt 706 contributes 85
through false Westhaven totals that replace `48*x + 15` with `36*x + 15`.
Prompt 1168 contributes 82 by replacing `20*x + 14` with `19*x + 14` before
forcing answer 2. After the semantic adjustment, issue-code counts are 290
`solver_equation_mismatch`, 113 `equation_mismatch`, and five
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 4.24% and occur at steps 4626,
4627, 4629, 4632, 4649, and 4650, peaking transiently at 37.6%; none survives
into the 12,800 saved rows. The saved rows contain one truncation at step 4633.
Mismatch KL stays at most 0.0053 and ends at 0.0002. Gradient norm stays at
most 0.2068 and ends at 0.0836. No NaN, OOM, NCCL failure, or persistent
rollout failure appears. The step-4650 trainer and orchestrator checkpoints,
eight distributed trainer shards, stable inference weights, 512 training
rows, and all 3,000 evaluation rows are complete.

Step 4675 rebounds to 23.55% on OP11–20 and 13.08% on OP15–20, while
OP21–25 reaches 4.40%. OP20 scores 6.50% on both released and executable
strict. The rolling last-ten-checkpoint means remain 6.80% released and 6.65%
executable, respectively 2.066 and 1.916 percentage points above the matched
strict-filter OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24,
and OP25 score 8.5%, 8.0%, 3.5%, 1.0%, and 1.0%, respectively. All executable
OP20–25 positives repeat previously solved problems, so cumulative breadth
remains 40, 43, 34, 25, 13, and seven prompts.

Across the full evaluation, 515/3,000 trajectories pass released strict and
508/3,000 pass the raw executable grader, for 98.64% raw precision. OP11 index
150 correctly derives two irrelevant Clearwater values, and OP15 index 44
correctly derives the irrelevant Northwood total as 10. The third
pure-extra-node row, recurring OP16 index 50, is invalid. Counting the two
benign rows gives 510 semantically valid trajectories, 99.03% semantic
precision, and five genuine defects. After the semantic adjustment,
issue-code counts are four `equation_mismatch`, three
`solver_equation_mismatch`, and one `unexpected_node`, with overlap.
Evaluation has no rollout errors, two truncations, and mixes adjacent
asynchronous policy versions 4674 and 4675.

The preceding train window has released-strict reward 0.3463 and
executable-strict success 0.3414, for 98.60% executable precision among 4,432
released passes. It has no pure-extra-node rejection, leaving 62 genuine
defects. Prompt 505 contributes 27 by claiming that `x + 66 + 27` equals
`x + 114`, then forcing answer 1. Prompt 1305 contributes seven by replacing
the correct Brightford total `16*x + 31` with `18*x + 25` before forcing
answer 4. Prompt 717 contributes four by adding the Clearwater elementary
school twice, replacing `x + 12` with `x + 15`, and forcing answer 2.
Issue-code counts are 52 `equation_mismatch`, 41
`solver_equation_mismatch`, two `undefined_symbol`, and one
`unsupported_expression`, with overlap.

Logged off-policy cancellation errors average 0.20% and occur only at step
4664, peaking transiently at 5.1%; none survives into the 12,800 saved rows.
The saved rows contain one truncation at step 4667. Mismatch KL spikes to
0.0135 at step 4672, falls to 0.0005 on step 4673, ends at 0.0019, and returns
to 0.0002 on step 4676. Gradient norm stays at most 0.4218 and ends at 0.0741.
No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-4675 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4700 records 23.75% on OP11–20, 13.83% on OP15–20, and 4.40% on
OP21–25. OP20 scores 8.00% on both released and executable strict. The rolling
last-ten-checkpoint means are 6.75% released and 6.60% executable,
respectively 2.016 and 1.866 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
10.0%, 8.0%, 2.5%, 1.0%, and 0.5%, respectively. OP20 index 18 is a new
executable success. Manual inspection confirms the Taylor total 20, both
Northwood components 38, and exact Northwood answer 96. Cumulative executable
OP20–25 breadth therefore becomes 41, 43, 34, 25, 13, and seven prompts.

Across the full evaluation, 519/3,000 trajectories pass released strict and
510/3,000 pass the executable grader, for 98.27% precision. Its sole
pure-extra-node row is recurring OP16 index 50, which is invalid, so all nine
rejections are genuine defects. Issue-code counts are six
`solver_equation_mismatch`, three `equation_mismatch`, and one each of
`undefined_symbol` and `unexpected_node`, with overlap. Evaluation has no
rollout errors, one truncation, and mixes adjacent asynchronous policy
versions 4699 and 4700.

The preceding train window has released-strict reward 0.5064 and raw
executable-strict success 0.4825, for 95.28% raw precision among 6,482 released
passes. Two prompts account for all 207 pure-extra-node rejections. All 122
prompt-765 rows correctly derive the irrelevant Mayer Aquarium crow count as
20. All 85 prompt-277 rows are invalid: the Clearwater regional-medical count
should be 15 from the Shoreline regional and elementary values, but 80 rows
derive 9 from the wrong elementary entity and five derive 6 while omitting a
term. Counting only the valid rows gives 6,298 semantically valid trajectories,
97.16% semantic precision, and 184 genuine defects. Prompt 583 contributes 38
by replacing `x + 58` with `x + 66` before forcing answer 4. Prompt 312
contributes 32 by replacing the correct Riverton total `15*x + 32` with
`17*x + 32`, again forcing answer 4. After the semantic adjustment,
issue-code counts are 94 `equation_mismatch`, 85 `unexpected_node`, 82
`solver_equation_mismatch`, and one `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 0.05% and occur only at step
4686, peaking transiently at 1.2%; none survives into the 12,800 saved rows.
The saved rows contain one truncation at step 4688. Mismatch KL spikes to
0.0103 at step 4685, returns to 0.0001 on step 4686, and ends at 0.0002.
Gradient norm stays at most 0.2982 and ends at 0.0565. No NaN, OOM, NCCL
failure, or persistent rollout failure appears. The step-4700 trainer and
orchestrator checkpoints, eight distributed trainer shards, stable inference
weights, 512 training rows, and all 3,000 evaluation rows are complete.

Step 4725 records 26.25% on OP11–20, 14.58% on OP15–20, and 4.30% on
OP21–25. OP20 scores 6.50% on both released and executable strict. The rolling
last-ten-checkpoint means are 6.85% released and 6.70% executable,
respectively 2.116 and 1.966 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score
7.5%, 7.0%, 4.5%, 2.0%, and 0.5%, respectively. New executable successes on
OP20 index 48, OP21 index 33, and OP22 index 0 expand cumulative executable
OP20–25 breadth to 42, 44, 35, 25, 13, and seven prompts.

Across the full evaluation, 568/3,000 trajectories pass released strict and
558/3,000 pass the raw executable grader, for 98.24% raw precision. Four rows
have only an `unexpected_node` issue. OP12 index 102 correctly derives the
irrelevant Verdi futuristic-sci-fi count, and OP13 index 54 correctly derives
the irrelevant Clairmont total, so both are benign. OP14 index 55 uses the
Ruby total in place of the Shoreline total, and OP16 index 50 derives the Mayer
deer count from the wrong zoo's bear count, so both are invalid. Counting the
two benign rows gives 560 semantically valid trajectories, 98.59% semantic
precision, and eight genuine defects. After this adjustment, issue-code counts
are six `solver_equation_mismatch`, four `equation_mismatch`, two
`unexpected_node`, and one `undefined_symbol`, with overlap. Evaluation has no
rollout errors, two truncations, and consistently uses policy version 4724.

The preceding train window has released-strict reward 0.3939 and raw
executable-strict success 0.3851, for 97.76% raw precision among 5,042 released
passes. All six pure-extra-node rejections are prompt 725 and correctly derive
the irrelevant Clearwater Bay private-middle-school count as `x + 4`.
Counting them as valid gives 4,935 semantically valid trajectories, 97.88%
semantic precision, and 107 genuine defects. Prompt 1211 contributes 34 by
reversing a subtraction to obtain -2 and then silently changing it to +2.
Prompt 551 contributes 16 through the compensating false equalities
`108 + 15 = 99` and `99 + 8 = 131`. Prompt 839 contributes 14 by changing
`x + 21 + 33` to `x + 66` and then reporting the solution to the correct
`x + 54` equation. After the semantic adjustment, issue-code counts are 102
`equation_mismatch` and 37 `solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 0.70% and occur only at step
4707, peaking transiently at 17.5%; none survives into the 12,800 saved rows.
The saved rows contain two truncations. Mismatch KL stays at most 0.0015 and
ends at 0.0001. At step 4718, two all-dropped batches are retried successfully
and gradient norm briefly reaches 2.4952; it returns to 0.0490 on step 4719
and ends at 0.0695. No NaN, OOM, NCCL failure, or persistent rollout failure
appears. The step-4725 trainer and orchestrator checkpoints, eight distributed
trainer shards, stable inference weights, 512 training rows, and all 3,000
evaluation rows are complete.

Step 4750 raises OP20 to 8.00% on both released and executable strict, 3.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means are 6.95% released and
6.90% executable, respectively 2.216 and 2.166 points above that SFT result.
The complete aggregates are 25.70% on OP11–20, 13.50% on OP15–20, and 3.20%
on OP21–25. OP21, OP22, OP23, OP24, and OP25 score 5.5%, 6.0%, 2.5%, 1.0%,
and 1.0%, respectively. No new OP20–25 prompt succeeds, so cumulative
executable breadth remains 42, 44, 35, 25, 13, and seven prompts.

Across the full evaluation, 546/3,000 trajectories pass released strict and
540/3,000 pass the executable grader, for 98.90% precision. The sole
pure-extra-node row is recurring OP14 index 55, which incorrectly substitutes
the Ruby total for the Shoreline total, so all six rejections are genuine
defects. Issue-code counts are four `equation_mismatch`, four
`solver_equation_mismatch`, and one `unexpected_node`, with overlap.
Evaluation has no rollout errors, one truncation, and mixes adjacent
asynchronous policy versions 4749 and 4750.

The preceding train window has released-strict reward 0.4445 and
executable-strict success 0.4405, for 99.10% executable precision among 5,689
released passes. All 51 rejections are genuine defects. Prompt 852 contributes
17 by changing `9*x + 19` to `11*x + 19` and then falsely solving the latter
equation as `x = 3`. Prompt 318 contributes 15 by replacing `2*x` with 2 in a
symbolic sum before forcing the correct answer 1. Prompt 1587 contributes
three by changing `13*x + 8` to `11*x + 8` and claiming `26 / 11 = 2`.
Issue-code counts are 48 `equation_mismatch`, 23
`solver_equation_mismatch`, and three `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.67% and occur only at step
4736, peaking transiently at 16.8%; none survives into the 12,800 saved rows.
The saved rows contain one truncation. Mismatch KL peaks at 0.0056 on step 4729
and ends at 0.0000. Gradient norm stays at most 0.5426 and ends at 0.0208. No
NaN, OOM, NCCL failure, or persistent rollout failure appears. The step-4750
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 4775 records 25.90% on OP11–20, 14.33% on OP15–20, and 4.00% on
OP21–25. OP20 scores 7.00% on both released and executable strict, 2.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means are both 6.75%, 2.016
points above that SFT result. OP21, OP22, OP23, OP24, and OP25 score 7.5%,
6.5%, 4.5%, 1.5%, and 0.0%, respectively. No new OP20–25 prompt succeeds, so
cumulative executable breadth remains 42, 44, 35, 25, 13, and seven prompts.

Across the full evaluation, 558/3,000 trajectories pass released strict and
545/3,000 pass the raw executable grader, for 97.67% raw precision. Three rows
have only an `unexpected_node` issue. OP11 index 112 correctly derives the
irrelevant West Sahara upbeat-comedy count as 45 and is benign. Recurring OP14
index 55 substitutes the Ruby total for the Shoreline total, while OP16 index
50 derives the Mayer deer count from the South Zoo bear count; both are
invalid. Counting the benign row gives 546 semantically valid trajectories,
97.85% semantic precision, and 12 genuine defects. After this adjustment,
issue-code counts are nine `solver_equation_mismatch`, eight
`equation_mismatch`, two `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, one truncation, and mixes adjacent
asynchronous policy versions 4774 and 4775.

The preceding train window has released-strict reward 0.3616 and
executable-strict success 0.3555, for 98.34% executable precision among 4,628
released passes. All 77 rejections are genuine defects. Prompt 973 contributes
27 by subtracting the Pine Ridge fox count where the Beverly Forest fox count
is required and then falsely solving `8*x + 4 = 30` as `x = 3`. Prompt 1209
contributes 24 through the compensating false equalities `29 + 29 = 64` and
`64 + 29 = 87`. Prompt 328 contributes 12 after constructing `7*x + 6`
instead of the correct total `11*x + 6` and claiming `22 / 7 = 2`.
Issue-code counts are 47 `equation_mismatch` and 43
`solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 1.45%, occurring only at steps
4753 and 4770 and peaking transiently at 18.4%; none survives into the 12,800
saved rows. The saved rows contain no truncations. Mismatch KL peaks at 0.0033
on step 4765 and ends at 0.0001. Gradient norm stays at most 0.7610 and ends at
0.0857. No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-4775 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4800 records 26.45% on OP11–20, 14.17% on OP15–20, and 4.10% on
OP21–25. OP20 scores 8.00% released strict and 7.50% executable strict. The
released estimate is 3.266 percentage points above the matched strict-filter
OP20 SFT checkpoint's 4.734% pass@1. The rolling last-ten-checkpoint means are
6.85% released and 6.80% executable, respectively 2.116 and 2.066 points above
that SFT result. OP21, OP22, OP23, OP24, and OP25 score 7.5%, 7.5%, 4.0%,
0.5%, and 1.0%, respectively. No new OP20–25 prompt succeeds, so cumulative
executable breadth remains 42, 44, 35, 25, 13, and seven prompts.

Across the full evaluation, 570/3,000 trajectories pass released strict and
554/3,000 pass the raw executable grader, for 97.19% raw precision. Both
pure-extra-node rows are benign: OP12 index 102 correctly derives the
irrelevant Verdi futuristic-sci-fi count as 2, and OP13 index 54 correctly
derives the irrelevant Clairmont total as 18. Counting them as valid gives 556
semantically valid trajectories, 97.54% semantic precision, and 14 genuine
defects. After this adjustment, issue-code counts are ten
`solver_equation_mismatch`, eight `equation_mismatch`, and one
`undefined_symbol`, with overlap. OP20 index 49 is the sole released-only OP20
pass: it uses the compensating false equalities `12 + 68 = 68` and
`68 + 34 = 114`. Evaluation has no rollout errors, one truncation, and mixes
adjacent asynchronous policy versions 4799 and 4800.

The preceding train window has released-strict reward 0.3240 and
executable-strict success 0.3209, for 99.06% executable precision among 4,147
released passes. Its sole pure-extra-node rejection, prompt 690, incorrectly
derives the Hawkesbury culinarian-school count from the Glenfield
private-middle-school count, so all 39 rejections are genuine defects. Prompt
1282 contributes 18 through the compensating false equalities
`112 + 20 = 120` and `120 + 4 = 136`. Prompt 464 contributes four by changing
the correct symbolic total `15*x + 8` to `19*x + 8` before forcing `x = 3`.
Prompt 382 contributes two by constructing `6*x + 2` instead of `8*x + 2`
and then falsely solving the former as `x = 4`. Issue-code counts are 34
`equation_mismatch`, 11 `solver_equation_mismatch`, and one `unexpected_node`,
with overlap.

The window has zero logged or saved rollout errors and zero train truncations.
Mismatch KL stays at most 0.0004 and ends at 0.0000. Gradient norm stays at
most 0.3751 and ends at 0.1464. No NaN, OOM, NCCL failure, or persistent
rollout failure appears. The step-4800 trainer and orchestrator checkpoints,
eight distributed trainer shards, stable inference weights, 512 training rows,
and all 3,000 evaluation rows are complete.

Step 4825 records 26.40% on OP11–20, 13.75% on OP15–20, and 4.10% on
OP21–25. OP20 scores 8.00% on both released and executable strict, 3.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means are 6.90% released and
6.85% executable, respectively 2.166 and 2.116 points above that SFT result.
OP21, OP22, OP23, OP24, and OP25 score 8.5%, 8.0%, 3.0%, 0.5%, and 0.5%,
respectively. OP22 index 23 is a new executable success, expanding cumulative
executable OP20–25 breadth to 42, 44, 36, 25, 13, and seven prompts.

Across the full evaluation, 569/3,000 trajectories pass released strict and
559/3,000 pass the executable grader, for 98.24% precision. The sole
pure-extra-node row, OP13 index 54, incorrectly reports the Clairmont total as
12 rather than 18, so all ten rejections are genuine defects. Issue-code
counts are eight `solver_equation_mismatch`, five `equation_mismatch`, and one
`unexpected_node`, with overlap. Evaluation has no rollout errors or
truncations and mixes adjacent asynchronous policy versions 4824 and 4825.

The preceding train window has released-strict reward 0.3942 and
executable-strict success 0.3832, for 97.21% executable precision among 5,046
released passes. Its sole pure-extra-node rejection, prompt 286, incorrectly
derives the Riverton regional-medical count, so all 141 rejections are genuine
defects. Prompt 235 contributes 60 by changing the correct symbolic total
`21*x + 4` to `23*x + 4` before forcing `x = 2`. Prompt 732 contributes 23 by
constructing `2*x + 36` instead of `3*x + 35` and then falsely solving the
former as `x = 4`. Prompt 565 contributes 16 through the compensating false
equalities `66 + 13 = 67` and `67 + 5 = 84`. These three repeated problems
account for 99/141 defects. Issue-code counts are 125 `equation_mismatch`, 102
`solver_equation_mismatch`, and one `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.69% and occur only at step
4801, peaking transiently at 17.3%; none survives into the 12,800 saved rows.
The saved rows contain no truncations. Mismatch KL peaks at 0.0012 on step 4816
and ends at 0.0003. Gradient norm stays at most 0.4354 and ends at 0.0457. No
NaN, OOM, NCCL failure, or persistent rollout failure appears. The step-4825
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 4850 records 26.10% on OP11–20, 13.75% on OP15–20, and 3.80% on
OP21–25. OP20 scores 7.50% on both released and executable strict, 2.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means reach 7.15% released and
7.10% executable, respectively 2.416 and 2.366 points above that SFT result.
OP21, OP22, OP23, OP24, and OP25 score 7.0%, 6.5%, 4.5%, 0.5%, and 0.5%,
respectively. No new OP20–25 prompt succeeds, so cumulative executable breadth
remains 42, 44, 36, 25, 13, and seven prompts.

Across the full evaluation, 560/3,000 trajectories pass released strict and
550/3,000 pass the raw executable grader, for 98.21% raw precision. OP11 index
112 correctly derives the irrelevant West Sahara upbeat-comedy count as 45,
and OP13 index 54 correctly derives the irrelevant Clairmont total as 18, so
both are benign. OP13 index 74 incorrectly sets the irrelevant Evervale
private-middle-school count to 5 rather than 3, and recurring OP14 index 55
substitutes the Ruby total for the Shoreline total, so both are invalid.
Counting the two benign rows gives 552 semantically valid trajectories, 98.57%
semantic precision, and eight genuine defects. After this adjustment,
issue-code counts are six `solver_equation_mismatch`, four
`equation_mismatch`, and two `unexpected_node`, with overlap. Evaluation has
no rollout errors, one truncation, and mixes adjacent asynchronous policy
versions 4849 and 4850.

The preceding train window has released-strict reward 0.4427 and
executable-strict success 0.4300, for 97.14% executable precision among 5,666
released passes. All 162 rejections are genuine defects. Prompt 580 contributes
88 by changing `22*x + 12` to `22*x + 18` and then claiming `60 / 22 = 3`.
Prompt 1353 contributes 37 through the compensating false equalities
`64 + 40 = 80` and `80 + 24 = 128`. Prompt 535 contributes 20 through
`8 + 128 = 160` followed by `160 + 24 = 160`. These three repeated problems
account for 145/162 defects. Issue-code counts are 139 `equation_mismatch`, 91
`solver_equation_mismatch`, seven each of `definition_dependency_mismatch` and
`definition_value_mismatch`, and one each of `expression_syntax` and
`undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 0.74% and occur only at step
4839, peaking transiently at 18.4%; none survives into the 12,800 saved rows.
The saved rows contain no truncations. Mismatch KL peaks at 0.0019 on step 4826
and ends at 0.0001. Gradient norm stays at most 0.2501 and ends at 0.1329. No
NaN, OOM, NCCL failure, or persistent rollout failure appears. The step-4850
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 4875 records 26.25% on OP11–20, 14.17% on OP15–20, and 4.60% on
OP21–25. OP20 scores 7.50% on both released and executable strict, 2.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means remain 7.15% released and
7.10% executable, respectively 2.416 and 2.366 points above that SFT result.
OP21, OP22, OP23, OP24, and OP25 score 9.5%, 8.0%, 3.5%, 1.0%, and 1.0%,
respectively. No new OP20–25 prompt succeeds, so cumulative executable breadth
remains 42, 44, 36, 25, 13, and seven prompts.

Across the full evaluation, 571/3,000 trajectories pass released strict and
561/3,000 pass the raw executable grader, for 98.25% raw precision. The sole
pure-extra-node row, OP13 index 54, correctly derives the irrelevant Clairmont
total as 18 and is benign. Counting it as valid gives 562 semantically valid
trajectories, 98.42% semantic precision, and nine genuine defects. After this
adjustment, issue-code counts are seven `solver_equation_mismatch` and five
`equation_mismatch`, with overlap. Evaluation has no rollout errors, one
truncation, and mixes adjacent asynchronous policy versions 4874 and 4875.

The preceding train window has released-strict reward 0.3711 and raw
executable-strict success 0.3525, for 94.99% raw precision among 4,750 released
passes. One of 142 pure-extra-node rejections, prompt 692, correctly derives
the irrelevant Hawkesbury total and Westhaven culinarian count. Prompt 277
contributes 115 invalid extras by deriving the Clearwater regional-medical
count as 9 rather than 15, while prompt 350 contributes 26 by deriving the
Jefferson wolf count as 11 rather than 13. Counting only the benign row gives
4,513 semantically valid trajectories, 95.01% semantic precision, and 237
genuine defects. Prompt 570 contributes another 48 by replacing the correct
symbolic total `x + 88` with `x + 72` before forcing `x = 3`. These three
problem clusters account for 189/237 genuine defects. After the semantic
adjustment, issue-code counts are 144 `unexpected_node`, 89
`equation_mismatch`, 76 `solver_equation_mismatch`, and one each of
`unsupported_expression` and `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.74% across steps 4851–4875,
occur at steps 4857–4859, and peak transiently at 21.4%; none survives into the
12,800 saved rows. The saved rows contain no truncations. Mismatch KL stays at
most 0.0004 and ends at 0.0003. Gradient norm stays at most 0.4809 and ends at
0.0724. No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-4875 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 4900 drops to 23.15% on OP11–20, 13.17% on OP15–20, and 3.50% on
OP21–25. OP20 scores 6.00% released strict and 5.50% executable strict. The
released estimate remains 1.266 percentage points above the matched
strict-filter OP20 SFT checkpoint's 4.734% pass@1. Despite this single-point
dip, the rolling last-ten-checkpoint means reach 7.30% released and 7.20%
executable, respectively 2.566 and 2.466 points above that SFT result. OP21,
OP22, OP23, OP24, and OP25 score 5.0%, 7.0%, 4.5%, 1.0%, and 0.0%,
respectively. OP22 indices 153 and 156 are new executable successes, expanding
cumulative executable OP20–25 breadth to 42, 44, 38, 25, 13, and seven prompts.

Across the full evaluation, 498/3,000 trajectories pass released strict and
486/3,000 pass the executable grader, for 97.59% precision. There is no
pure-extra-node rejection, so all 12 defects are genuine. Issue-code counts are
nine `solver_equation_mismatch` and six `equation_mismatch`, with overlap.
OP20 index 99 is the sole released-only OP20 pass: it reuses a variable and
claims `13 + 12 = 25` in an equality whose left-hand side evaluates to 26.
Evaluation has no rollout errors, one truncation, and mixes adjacent
asynchronous policy versions 4899 and 4900.

The preceding train window has released-strict reward 0.4509 and raw
executable-strict success 0.4396, for 97.49% raw precision among 5,772 released
passes. All 19 pure-extra-node rejections are benign: 17 correctly derive the
Jefferson eagle count, and the two singleton rows correctly derive irrelevant
Evervale-school and Jefferson-deer values. Counting them as valid gives 5,646
semantically valid trajectories, 97.82% semantic precision, and 126 genuine
defects. Prompt 627 contributes 36 through the compensating false equalities
`120 - 8 = 92` and `3 * 92 = 336`. Prompt 1126 contributes 34 by deriving the
correct equation `25*x + 8 = 108`, then changing the solver residual from 100
to 80 and claiming `80 / 25 = 4`. Prompt 588 contributes 31 by changing the
correct symbolic total `15*x + 32` to `17*x + 32` before forcing `x = 2`.
These three problem clusters account for 101/126 genuine defects. After the
semantic adjustment, issue-code counts are 119 `equation_mismatch` and 74
`solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 3.01% across steps 4876–4900,
occur at four isolated steps, and peak transiently at 23.1%; none survives into
the 12,800 saved rows. The saved rows contain one truncation at step 4890.
Mismatch KL peaks at 0.0049 on step 4896 and ends at 0.0003. Gradient norm
stays at most 0.5237 and ends at 0.1279. No NaN, OOM, NCCL failure, or
persistent rollout failure appears. The step-4900 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 4925 records 22.80% on OP11–20, 12.58% on OP15–20, and 4.50% on
OP21–25. OP20 rebounds to 7.50% on both released and executable strict, 2.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means reach 7.40% released and
7.30% executable, respectively 2.666 and 2.566 points above that SFT result.
OP21, OP22, OP23, OP24, and OP25 score 7.5%, 8.0%, 4.5%, 2.0%, and 0.5%,
respectively. No new OP20–25 prompt succeeds, so cumulative executable breadth
remains 42, 44, 38, 25, 13, and seven prompts.

Across the full evaluation, 501/3,000 trajectories pass released strict and
490/3,000 pass the raw executable grader, for 97.80% raw precision. OP13 index
54 correctly derives the irrelevant Clairmont total as 18 and is benign.
OP13 index 74 incorrectly sets the Evervale private-middle-school count to 5
rather than 3; recurring OP14 index 55 and OP16 index 50 also derive incorrect
irrelevant nodes. Counting only the benign row gives 491 semantically valid
trajectories, 98.00% semantic precision, and ten genuine defects. After this
adjustment, issue-code counts are six `solver_equation_mismatch`, three each of
`equation_mismatch` and `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, two truncations, and mixes adjacent
asynchronous policy versions 4924 and 4925.

The preceding train window has released-strict reward 0.4895 and raw
executable-strict success 0.4717, for 96.38% raw precision among 6,265 released
passes. Of 132 pure-extra-node rejections, 109 prompt-154 rows correctly derive
the irrelevant Oakridge bear count as 24 and are benign. Eighteen prompt-156
rows derive the Jefferson parrot count as 4 rather than 5, prompt 544 derives
the South Zoo total as 21 rather than 19, and four prompt-1539 rows derive the
Cedar Valley crow count as 23 rather than 19; these 23 rows are invalid.
Counting the benign rows gives 6,147 semantically valid trajectories, 98.12%
semantic precision, 0.4802 semantically clean reward, and 118 genuine defects.
Prompt 1400 contributes 28 through `84 + 4 = 76` followed by `76 + 2 = 90`.
Prompt 312 contributes 26 by changing `15*x + 32` to `17*x + 32` before
forcing `x = 4`. Prompt 1553 contributes 22 through `27 + 48 = 99` followed by
`99 + 24 = 99`. These three problem clusters account for 76/118 genuine
defects. After the semantic adjustment, issue-code counts are 93
`equation_mismatch`, 28 `solver_equation_mismatch`, and 24 `unexpected_node`,
with overlap.

Logged off-policy cancellation errors average 2.14% across steps 4901–4925,
occur at three isolated steps, and peak transiently at 20.7%; none survives
into the 12,800 saved rows. The saved rows contain no truncations. Mismatch KL
stays at most 0.0004 and ends at 0.0000. Gradient norm stays at most 0.2169 and
ends at 0.0418. No NaN, OOM, NCCL failure, or persistent rollout failure
appears. The step-4925 trainer and orchestrator checkpoints, eight distributed
trainer shards, stable inference weights, 512 training rows, and all 3,000
evaluation rows are complete.

Step 4950 records 23.85% on OP11–20, 12.58% on OP15–20, and 4.70% on
OP21–25. OP20 scores 7.00% on both released and executable strict, 2.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means are 7.30% released and
7.20% executable, respectively 2.566 and 2.466 points above that SFT result.
OP21, OP22, OP23, OP24, and OP25 score 9.0%, 7.5%, 5.0%, 1.0%, and 1.0%,
respectively. No new OP20–25 prompt succeeds, so cumulative executable breadth
remains 42, 44, 38, 25, 13, and seven prompts.

Across the full evaluation, 524/3,000 trajectories pass released strict and
512/3,000 pass the executable grader, for 97.71% precision. The sole
pure-extra-node row is recurring OP14 index 55, which derives the Shoreline
elementary-school count from the wrong total, so all 12 rejections are genuine.
Issue-code counts are nine `solver_equation_mismatch`, five
`equation_mismatch`, and one each of `undefined_symbol` and `unexpected_node`,
with overlap. Evaluation has no rollout errors, one truncation, and mixes
adjacent asynchronous policy versions 4949 and 4950.

The preceding train window exposes a materially larger verifier weakness.
Released-strict reward is 0.4087, while raw executable-strict success is
0.3584, only 87.71% raw precision among 5,231 released passes. Of 241
pure-extra-node rejections, 124 prompt-765 rows correctly derive the irrelevant
Mayer crow count, five prompt-666 rows correctly derive the Rêves de Belleville
total, and five prompt-1559 rows correctly derive the South Zoo deer count.
These 134 rows are benign. Conversely, 107 prompt-1082 rows incorrectly derive
the Evervale culinarian-school count as 5 rather than the Westhaven total 21.
Counting the benign rows gives 4,722 semantically valid trajectories, 90.27%
semantic precision, 0.3689 semantically clean reward, and 509 genuine defects.

Prompt 62 contributes 121 by replacing the correct total `20 - x` with a
self-overwriting `2*x + 20` expression and then claiming `3 / 2 = 3`. Prompt
1168 contributes 80 by replacing `20*x + 14` with `19*x + 14` and claiming
`46 / 19 = 2`. Prompt 515 contributes 69 by double-counting the Ruby
culinarian term, producing `40*x` rather than `38*x`, then claiming
`114 / 40 = 3`. Together with the 108-row prompt-1082 cluster, these four
problems account for 378/509 genuine defects. After the semantic adjustment,
issue-code counts are 371 `solver_equation_mismatch`, 291
`equation_mismatch`, 109 `unexpected_node`, two `expression_syntax`, and one
`undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.13% and occur only at steps
4938 and 4942, peaking transiently at 20.9%; none survives into the 12,800
saved rows. The saved rows contain no truncations. Mismatch KL peaks and ends
at 0.0031 on step 4950, then recovers to 0.0006 by step 4958. Gradient norm
stays at most 0.7501 and ends at 0.0630. No NaN, OOM, NCCL failure, or
persistent rollout failure appears. The step-4950 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 4975 rebounds to 24.65% on OP11–20, 13.25% on OP15–20, and 4.40% on
OP21–25. OP20 scores 7.50% on both released and executable strict, 2.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means return to 7.40% released
and 7.30% executable, respectively 2.666 and 2.566 points above that SFT
result. OP21, OP22, OP23, OP24, and OP25 score 8.5%, 7.0%, 4.5%, 1.0%, and
1.0%, respectively. OP21 index 86 is a new executable success, expanding
cumulative executable OP20–25 breadth to 42, 45, 38, 25, 13, and seven prompts.

Across the full evaluation, 537/3,000 trajectories pass released strict and
524/3,000 pass the raw executable grader, for 97.58% raw precision. OP11
indices 15 and 58 correctly derive irrelevant Beverly Forest values, while
OP12 index 102 correctly derives the irrelevant Verdi futuristic-sci-fi count;
all three are benign. Recurring OP14 index 55 derives the Shoreline elementary
count from the wrong total and is invalid. Counting the benign rows gives 527
semantically valid trajectories, 98.14% semantic precision, and ten genuine
defects. After this adjustment, issue-code counts are seven each of
`equation_mismatch` and `solver_equation_mismatch`, and one `unexpected_node`,
with overlap. Evaluation has no rollout errors, one truncation, and mixes
adjacent asynchronous policy versions 4974 and 4975.

The preceding train window has released-strict reward 0.3656 and raw
executable-strict success 0.3536, for 96.71% raw precision among 4,680 released
passes. Prompt 725 correctly derives the irrelevant Clearwater private-middle
count and is benign. Prompt 271 invents an unsupported Glenfield
private-middle-school node and is invalid. Counting only the benign row gives
4,527 semantically valid trajectories, 96.73% semantic precision, 0.3537
semantically clean reward, and 153 genuine defects. This is a sharp recovery
from the 90.27% semantic precision in the preceding step-4950 window.

Prompt 567 contributes 75 by clobbering a symbolic variable and changing the
correct total `11*x + 15` to `15*x + 15` before forcing `x = 4`. Prompt 768
contributes 15 by changing `39*x` to `51*x` and claiming `117 / 51 = 3`.
Prompt 662 contributes 14 by changing the correct total `x + 127` to
`x + 148`, then solving a contradictory `x + 64 = 131` equation as `x = 4`.
These three problem clusters account for 104/153 genuine defects. After the
semantic adjustment, issue-code counts are 149 `equation_mismatch`, 129
`solver_equation_mismatch`, and one each of `unexpected_node` and
`expression_syntax`, with overlap.

Logged off-policy cancellation errors average 2.23% and occur only at steps
4957 and 4974, peaking transiently at 37.0%; none survives into the 12,800
saved rows. The saved rows contain one truncation at step 4971. Mismatch KL
stays at most 0.0013 and ends at 0.0001. Gradient norm stays at most 0.4870 and
ends at 0.0441. No NaN, OOM, NCCL failure, or persistent rollout failure
appears. The step-4975 trainer and orchestrator checkpoints, eight distributed
trainer shards, stable inference weights, 512 training rows, and all 3,000
evaluation rows are complete.

Step 5000 reaches 25.20% on OP11–20, 13.92% on OP15–20, and 5.30% on
OP21–25. OP20 scores 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means are 7.20% released and
7.10% executable, respectively 2.466 and 2.366 points above that SFT result.
OP21, OP22, OP23, OP24, and OP25 score 9.0%, 10.5%, 4.0%, 2.5%, and 0.5%,
respectively. OP21 index 53 is a new executable success, expanding cumulative
executable OP20–25 breadth to 42, 46, 38, 25, 13, and seven prompts.

Across the full evaluation, 557/3,000 trajectories pass released strict and
548/3,000 pass the executable grader, for 98.38% precision. The sole
pure-extra-node row is OP16 index 50: it substitutes the South Zoo bear count
42 into a Mayer chain and derives 45 instead of the supported Mayer value 7.
It is invalid, so all nine executable rejections are genuine. Issue-code
counts are six `equation_mismatch`, five `solver_equation_mismatch`, one
`undefined_symbol`, and one `unexpected_node`, with overlap. Evaluation has
no rollout errors, three truncations, and mixes adjacent asynchronous policy
versions 4999 and 5000.

The preceding train window has released-strict reward 0.3413 and executable
strict success 0.3355, for 98.33% precision among 4,368 released passes. The
two pure-extra-node prompt-259 rows add a Festival Saint-Rivage total by
unsupportedly equating it with one genre count; both are invalid. All 73
executable rejections are therefore genuine. Prompt 457 contributes 22 by
overwriting a symbolic variable and changing the grader state `12*x + 16`
into a claimed `13*x + 20` before forcing answer 2. Prompt 903 contributes 21
by changing the correct total `9*x + 5` to `5*x + 5`, then falsely solving it
as answer 3. Prompt 104 contributes 12 by changing `7*x + 20` to `7*x + 18`
before forcing answer 3. These three clusters account for 55/73 defects.
Issue-code counts are 63 `equation_mismatch`, 62
`solver_equation_mismatch`, three `unexpected_node`, and one each of
`undefined_symbol`, `definition_dependency`, and `definition_value`, with
overlap.

Logged off-policy cancellation errors average 1.32%, occur only at steps 4981
and 4987, and peak transiently at 16.8%; none survives into the 12,800 saved
rows. The saved rows contain no truncations. Mismatch KL stays at most 0.0006
and ends at 0.0004. Gradient norm stays at most 0.3862 and ends at 0.0715. No
NaN, OOM, NCCL failure, or persistent rollout failure appears. The step-5000
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows
are complete.

Step 5025 reaches 25.40% on OP11–20, 13.17% on OP15–20, and 4.80% on
OP21–25. OP20 scores 8.50% on both released and executable strict, 3.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means rise to 7.35% released
and 7.25% executable, respectively 2.616 and 2.516 points above that SFT
result. OP21, OP22, OP23, OP24, and OP25 score 9.5%, 8.5%, 3.5%, 2.5%, and
0.0%, respectively. All executable OP20–25 positives repeat previously solved
problems, so cumulative breadth remains 42, 46, 38, 25, 13, and seven prompts.

Across the full evaluation, 556/3,000 trajectories pass released strict and
546/3,000 pass the raw executable grader, for 98.20% raw precision. OP13 index
54 correctly derives the irrelevant Festival de Clairmont total as 18 and is
the sole benign rejection. OP14 index 55 derives an extra Shoreline value from
the wrong total, OP16 index 50 substitutes the South Zoo bear count into a
Mayer chain, and OP19 index 16 invents a Riverton node absent from the prompt;
the other six rows contain direct arithmetic, solver, or symbol errors.
Counting the benign row gives 547 semantically valid trajectories, 98.38%
semantic precision, and nine genuine defects. After that adjustment,
issue-code counts are six `solver_equation_mismatch`, three
`equation_mismatch`, three `unexpected_node`, and one `undefined_symbol`, with
overlap. Evaluation has no rollout errors, one truncation, and mixes adjacent
asynchronous policy versions 5024 and 5025.

The preceding train window has released-strict reward 0.4666 and executable
strict success 0.4547, for 97.44% precision among 5,973 released passes. The
seven pure-extra-node prompt-97 rows are invalid because they set the stated
Oakbridge-dependent Riverton value from a different Riverton count. All 153
executable rejections are therefore genuine. Prompt 705 contributes 45 by
changing `8*x + 5` to `14*x + 5` and then claiming that adding `32*x + 20`
yields `40*x + 25`, forcing answer 2. Prompt 973 contributes 21 by changing
`9*x + 2` to `5*x + 2`, then falsely solving `5*x + 3 = 30` as answer 3.
Prompt 215 contributes 18 by obtaining `-2` and then writing
`2 * -2 = 2 * 2 = 4`. These three clusters account for 84/153 defects.
Issue-code counts are 124 `equation_mismatch`, 97
`solver_equation_mismatch`, 19 `unexpected_node`, and 12
`definition_dependency_mismatch`, with overlap.

No off-policy cancellation error or truncation appears in the logged or saved
12,800 training trajectories. Mismatch KL peaks transiently at 0.0046 and
ends at 0.0001. Gradient norm stays at most 0.2046 and ends at 0.0509. No NaN,
OOM, NCCL failure, or persistent rollout failure appears. The step-5025
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows
are complete.

Step 5050 reaches 24.45% on OP11–20, 12.92% on OP15–20, and 3.90% on
OP21–25. OP20 rises to 9.00% on both released and executable strict, 4.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means also rise to 7.45%
released and 7.40% executable, respectively 2.716 and 2.666 points above the
SFT result. OP21, OP22, OP23, OP24, and OP25 score 5.0%, 8.5%, 5.0%, 0.5%,
and 0.5%, respectively. OP22 index 149 coherently derives three animal totals
ending at 52, while OP23 index 75 coherently derives the Evervale, Brightford,
and Westhaven school totals ending at 144. These new executable successes
expand cumulative OP20–25 breadth to 42, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 528/3,000 trajectories pass released strict and
515/3,000 pass the raw executable grader, for 97.54% raw precision. OP11 index
112 correctly derives the irrelevant West Sahara genre count as 45, and OP13
index 54 correctly derives the irrelevant Festival de Clairmont total as 18;
both are benign. OP16 index 50 again substitutes the South Zoo bear count into
a Mayer chain and is invalid. The remaining rows contain direct arithmetic,
solver, or symbol errors. Counting the two benign rows gives 517 semantically
valid trajectories, 97.92% semantic precision, and 11 genuine defects. After
that adjustment, issue-code counts are eight each of `equation_mismatch` and
`solver_equation_mismatch`, and one each of `unexpected_node` and
`undefined_symbol`, with overlap. Evaluation has no rollout errors or
truncations and mixes adjacent asynchronous policy versions 5049 and 5050.

The preceding train window has released-strict reward 0.4323 and raw
executable-strict success 0.4227, for 97.80% raw precision among 5,533
released passes. Prompt 490 correctly derives the irrelevant Brightford
elementary-school count as 27 and is benign. Prompt 498 invents an unsupported
Evervale total by adding the same private-middle count twice. Prompt 942's
extra Bundle Ranch blue-jay value is numerically 2 but uses the Hamilton owl
as its dependency instead of the stated South Zoo blue jay, so it is invalid.
Counting only the benign row gives 5,412 semantically valid trajectories,
97.81% semantic precision, 0.4228 semantically clean reward, and 121 genuine
defects.

Prompt 395 contributes 19 by changing the correct `x + 68` total to
`x + 56`, then claiming that equation yields answer 3. Prompt 1898 contributes
13 by writing `36 + 44 = 92` and then `92 + 4 = 84`. Prompt 704 contributes
11 by changing `7*x + 13` to `6*x + 13`, then falsely solving it as answer 1.
These three clusters account for 43/121 genuine defects. After the semantic
adjustment, issue-code counts are 87 `equation_mismatch`, 78
`solver_equation_mismatch`, 11 `unexpected_node`, and one each of
`expression_syntax` and `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 2.08%, occur only at steps
5028, 5029, and 5047, and peak transiently at 17.8%; none survives into the
12,800 saved rows. The saved rows contain no truncations. Mismatch KL stays at
most 0.0003 and ends at 0.0003. Gradient norm reaches 0.6686, ends the window
at 0.2390, and recovers to 0.0260 by step 5057. No NaN, OOM, NCCL failure, or
persistent rollout failure appears. The step-5050 trainer and orchestrator
checkpoints, eight distributed trainer shards, stable inference weights, 512
training rows, and all 3,000 evaluation rows are complete.

Step 5075 reaches 24.85% on OP11–20, 13.75% on OP15–20, and 4.90% on
OP21–25. OP20 scores 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means are 7.25% released and
7.20% executable, respectively 2.516 and 2.466 points above the SFT result.
OP21, OP22, OP23, OP24, and OP25 score 9.5%, 10.0%, 3.0%, 1.5%, and 0.5%,
respectively. All executable OP20–25 positives repeat previously solved
problems, so cumulative breadth remains 42, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 546/3,000 trajectories pass released strict and
529/3,000 pass the raw executable grader, for 96.89% raw precision. OP11 index
152 correctly derives the irrelevant Bundle Ranch crow count as 6, OP12 index
102 correctly derives the irrelevant Verdi futuristic and total counts as 2
and 7, and OP15 index 188 correctly derives the irrelevant Maple Creek owl and
crow counts as 2; all three rows are benign. OP14 index 55 again derives the
extra Shoreline value from the wrong total and is invalid. The remaining rows
contain direct arithmetic or solver errors. Counting the three benign rows
gives 532 semantically valid trajectories, 97.44% semantic precision, and 14
genuine defects. After that adjustment, issue-code counts are ten each of
`equation_mismatch` and `solver_equation_mismatch`, and one `unexpected_node`,
with overlap. Evaluation has no rollout errors, one truncation, and mixes
asynchronous policy versions 5074, 5075, and 5076.

The preceding train window has released-strict reward 0.3932 and raw
executable-strict success 0.3810, for 96.90% raw precision among 5,033
released passes. Prompt 698 contributes 81 rows that correctly derive the
irrelevant Hawkesbury private-middle count as 6, so they are benign. Prompt
906 instead assigns the Evervale elementary count from the Glenfield
culinarian count rather than the stated Glenfield elementary count. Prompt 0
also replaces the stated Rêves de Belleville total with one genre count while
deriving the extra Saint-Rivage comedy value. Those two extra-node rows are
invalid. Counting the 81 benign rows gives 4,958 semantically valid
trajectories, 98.51% semantic precision, 0.3873 semantically clean reward, and
75 genuine defects.

Prompt 318 contributes 16 by replacing the correct `3*x + 4` total with
`x + 6`, although both happen to give answer 1. Prompt 551 contributes 13 by
writing `15 + 108 = 99` and then `99 + 8 = 131`. Prompt 1646 contributes 12
by correctly deriving `29*x + 8 = 66` but then changing the solver equation to
`29*x = 66` while retaining answer 2. These three clusters account for 41/75
genuine defects. After the semantic adjustment, issue-code counts are 53
`equation_mismatch`, 35 `solver_equation_mismatch`, and two
`unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.70%, occur only at step 5064,
and peak transiently at 17.5%; none survives into the 12,800 saved rows. The
saved rows contain one truncation at step 5054. Mismatch KL stays at most
0.0004 and ends at zero. Gradient norm stays at most 0.1872 and ends at
0.0611. No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-5075 trainer and orchestrator checkpoints, eight distributed trainer
shards, stable inference weights, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 5100 reaches 24.35% on OP11–20, 12.33% on OP15–20, and 4.20% on
OP21–25. OP20 scores 5.50% on both released and executable strict, 0.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means remain 7.05% released and
7.00% executable, respectively 2.316 and 2.266 points above the SFT result.
OP21, OP22, OP23, OP24, and OP25 score 9.0%, 7.0%, 4.0%, 1.0%, and 0.0%,
respectively. All executable OP20–25 positives repeat previously solved
problems, so cumulative breadth remains 42, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 529/3,000 trajectories pass released strict and
518/3,000 pass the raw executable grader, for 97.92% raw precision. OP13 index
54 correctly derives the irrelevant Festival de Clairmont total as 18 and is
benign. OP11 index 16 instead derives an extra Jefferson deer count as 21,
although the prompt supports 24, and OP16 index 50 again substitutes the South
Zoo bear count into a Mayer chain; both are invalid. The remaining rows contain
direct arithmetic or solver errors. Counting the benign row gives 519
semantically valid trajectories, 98.11% semantic precision, and ten genuine
defects. After that adjustment, issue-code counts are seven
`solver_equation_mismatch`, three `equation_mismatch`, and two
`unexpected_node`, with overlap. Evaluation has no rollout errors or
truncations and mixes asynchronous policy versions 5099, 5100, and 5101.

The preceding train window has released-strict reward 0.5161 and executable
strict success 0.5077, for 98.37% precision among 6,606 released passes. No
pure-extra-node rejection appears, and all 108 executable rejections are
genuine. Prompt 1219 contributes 64 by writing `84 + 16 = 112` and then
`112 + 2 = 102`. Prompt 557 contributes nine by writing `50 + 36 = 74` and
then `74 + 4 = 90`. Prompt 598 contributes six by changing the correct
`4*x + 7` total to `7*x + 7`, then falsely solving it as answer 2. These three
clusters account for 79/108 defects. Issue-code counts are 107
`equation_mismatch`, 14 `solver_equation_mismatch`, and one each of
`unexpected_node` and `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.52%, occur only at steps 5083
and 5084, and peak transiently at 20.8%; none survives into the 12,800 saved
rows. The saved rows contain no truncations. Mismatch KL stays at most 0.0006
and ends at zero. Gradient norm stays at most 0.3323, ends at 0.1496, and
recovers to 0.0131 by step 5102. No NaN, OOM, NCCL failure, or persistent
rollout failure appears. The step-5100 trainer and orchestrator checkpoints,
eight distributed trainer shards, stable inference weights, 512 training rows,
and all 3,000 evaluation rows are complete.

Step 5125 reaches 24.45% on OP11–20, 12.67% on OP15–20, and 4.00% on
OP21–25. OP20 scores 6.00% on both released and executable strict, 1.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means are 6.90% released and
6.85% executable, respectively 2.166 and 2.116 points above the SFT result.
OP21, OP22, OP23, OP24, and OP25 score 6.5%, 7.5%, 4.0%, 1.5%, and 0.5%,
respectively. All executable OP20–25 positives repeat previously solved
problems, so cumulative breadth remains 42, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 529/3,000 trajectories pass released strict and
516/3,000 pass the raw executable grader, for 97.54% raw precision. OP13 index
54 correctly derives the irrelevant Festival de Clairmont total as 18 and is
benign. Every other rejected row has a direct arithmetic, solver, or symbol
error. Counting the benign row gives 517 semantically valid trajectories,
97.73% semantic precision, and 12 genuine defects. After that adjustment,
issue-code counts are 11 `solver_equation_mismatch`, eight
`equation_mismatch`, and one `undefined_symbol`, with overlap. Evaluation has
no rollout errors, one truncation, and mixes asynchronous policy versions
5124, 5125, and 5126.

The preceding train window has released-strict reward 0.4848 and raw
executable-strict success 0.4634, for 95.58% raw precision among 6,205
released passes. Two prompt-86 rows correctly derive the irrelevant
Hawkesbury public-high-school count as 36 and are benign. Counting them gives
5,933 semantically valid trajectories, 95.62% semantic precision, 0.4635
semantically clean reward, and 272 genuine defects.

Prompt 1304 contributes 59 by replacing the correct `8*x + 42` total with
`14*x + 48`, while retaining answer 3. Prompt 1184 contributes 52 by changing
the correct `44*x + 2` total to `31*x + 2`, then retaining answer 2 despite
displaying `90 / 31`. Prompt 378 contributes 52 by changing `9*x + 36` to
`13*x + 36`, then falsely solving it as answer 3. These three clusters account
for 163/272 genuine defects. After the semantic adjustment, issue-code counts
are 225 `equation_mismatch` and 218 `solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 1.46%, occur only at steps 5101
and 5107, and peak transiently at 19.1%; none survives into the 12,800 saved
rows. The saved rows contain no truncations. Mismatch KL stays at most 0.0003
and ends at 0.0002. Gradient norm reaches 0.6266 and ends at 0.0602. No NaN,
OOM, NCCL failure, or persistent rollout failure appears. The step-5125
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows
are complete.

Step 5150 rebounds to 26.10% on OP11–20, 13.92% on OP15–20, and 3.40% on
OP21–25. OP20 rises to 9.00% on both released and executable strict, 4.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means return to 7.20% for both
released and executable strict, 2.466 points above the SFT result. OP21, OP22,
OP23, OP24, and OP25 score 8.0%, 5.0%, 3.0%, 0.5%, and 0.5%, respectively.
All executable OP20–25 positives repeat previously solved problems, so
cumulative breadth remains 42, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 556/3,000 trajectories pass released strict and
543/3,000 pass the raw executable grader, for 97.66% raw precision. OP13 index
54 correctly derives the irrelevant Festival de Clairmont total as 18 and is
benign. OP16 index 50 again substitutes the South Zoo bear count into a Mayer
chain and is invalid; every other rejected row contains a direct arithmetic,
syntax, or solver error. Counting the benign row gives 544 semantically valid
trajectories, 97.84% semantic precision, and 12 genuine defects. After that
adjustment, issue-code counts are seven each of `equation_mismatch` and
`solver_equation_mismatch`, and one each of `expression_syntax` and
`unexpected_node`, with overlap. Evaluation has no rollout errors or
truncations and mixes adjacent asynchronous policy versions 5149 and 5150.

The preceding train window has released-strict reward 0.3962 and executable
strict success 0.3872, for 97.73% precision among 5,071 released passes.
Prompt 123's pure-extra-node row derives the Evervale private-middle value as
8 instead of the prompt-supported 7, then invents an unsupported Evervale
total of 18; it is invalid. All 115 executable rejections are therefore
genuine.

Prompt 597 contributes 58 by replacing the correct `8*x + 12` total with
`11*x + 12`, while retaining answer 1. Prompt 596 contributes nine by changing
the correct `2*x + 4` total to `x + 6`, while retaining answer 2. Prompt 1301
contributes seven by correctly deriving `26*x + 7 = 85` but then changing the
solver equation from `26*x = 78` to `26*x = 72`, while retaining answer 3.
These three clusters account for 74/115 defects. Issue-code counts are 96
`equation_mismatch`, 73 `solver_equation_mismatch`, six `undefined_symbol`,
and one each of `unexpected_node` and `unsupported_expression`, with overlap.

Logged off-policy cancellation errors average 2.50%, occur at steps 5126,
5132, 5143, and 5149, and peak transiently at 19.0%; none survives into the
12,800 saved rows. The saved rows contain one truncation at step 5131.
Mismatch KL stays at most 0.0007 and ends at 0.0001. Gradient norm stays at
most 0.3257 and ends at 0.0504. No NaN, OOM, NCCL failure, or persistent
rollout failure appears. The step-5150 trainer and orchestrator checkpoints,
eight distributed trainer shards, stable inference weights, 512 training rows,
and all 3,000 evaluation rows are complete.

Step 5175 reaches 25.65% on OP11–20, 13.92% on OP15–20, and 4.50% on
OP21–25. OP20 scores 8.00% on both released and executable strict, 3.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means are 7.25% for both
released and executable strict, 2.516 points above the SFT result. OP21, OP22,
OP23, OP24, and OP25 score 8.0%, 9.5%, 3.5%, 1.5%, and 0.0%, respectively.
OP20 index 90 is a new coherent executable success: it derives the Ruby Bay,
Oakbridge City, and Shoreline City school values in dependency order to answer
75. Cumulative executable OP20–25 breadth therefore becomes 43, 46, 39, 26,
13, and seven prompts.

Across the full evaluation, 558/3,000 trajectories pass released strict and
550/3,000 pass the executable grader, for 98.57% precision. The sole
pure-extra-node row is recurring OP16 index 50, which substitutes the South
Zoo bear count into a Mayer chain and is invalid. Every rejection is therefore
genuine. Issue-code counts are seven `solver_equation_mismatch`, four
`equation_mismatch`, and one `unexpected_node`, with overlap. Evaluation has
no rollout errors or truncations and mixes adjacent asynchronous policy
versions 5174 and 5175.

The preceding train window has released-strict reward 0.3961 and executable
strict success 0.3858, for 97.40% precision among 5,070 released passes. No
pure-extra-node rejection appears, and all 132 executable rejections are
genuine. Prompt 590 contributes 86 by correctly deriving `23*x + 48 = 117`
but then replacing `23*x = 69` with `23*x = 60`, while retaining answer 3.
Prompt 645 contributes 12 by overwriting a symbolic variable and displaying
incompatible `30*x + 48` and `24*x + 39` expressions. Prompt 372 contributes
11 by changing the correct `5*x + 3` total to `7*x + 3`, while retaining
answer 2. These three clusters account for 109/132 defects. Issue-code counts
are 117 `solver_equation_mismatch`, 62 `equation_mismatch`, and one
`expression_syntax`, with overlap.

Logged off-policy cancellation errors average 1.23%, occur only at step 5170,
and peak transiently at 30.8%; none survives into the 12,800 saved rows. The
saved rows contain one truncation at step 5164. Mismatch KL stays at most
0.0003 and ends at zero. Gradient norm reaches 0.6188 and ends at 0.0503. No
NaN, OOM, NCCL failure, or persistent rollout failure appears. The step-5175
trainer and orchestrator checkpoints, eight distributed trainer shards,
stable inference weights, 512 training rows, and all 3,000 evaluation rows
are complete.

Step 5200 reaches 25.15% on OP11–20, 13.83% on OP15–20, and 4.30% on
OP21–25. OP20 scores 7.50% on both released and executable strict, 2.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means rise to 7.30% for both
released and executable strict, 2.566 points above the SFT result. OP21, OP22,
OP23, OP24, and OP25 score 8.5%, 8.0%, 4.0%, 0.5%, and 0.5%, respectively.
All executable OP20–25 positives repeat previously solved problems, so
cumulative breadth remains 43, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 546/3,000 trajectories pass released strict and
537/3,000 pass the executable grader, for 98.35% precision. Every rejection
has a direct arithmetic or solver error; no pure-extra-node discrepancy
appears. Issue-code counts are eight `equation_mismatch` and six
`solver_equation_mismatch`, with overlap. Evaluation has no rollout errors or
truncations and mixes adjacent asynchronous policy versions 5199 and 5200.

The preceding train window has released-strict reward 0.3673 and executable
strict success 0.3513, for 95.64% precision among 4,702 released passes. No
pure-extra-node rejection appears, and all 205 executable rejections are
genuine. Prompt 706 contributes 90 by changing the correct `48*x + 15` total
to `36*x + 15`, while retaining answer 1. Prompt 587 contributes 23 by
changing the correct `7*x + 20` total to `11*x + 31`, then retaining answer 1
despite displaying `8 / 11`. Prompt 1211 contributes 20 by reversing a
subtraction to obtain `-2`, then writing `4 * -2 = 4 * 2 = 8`. These three
clusters account for 133/205 defects. Issue-code counts are 204
`equation_mismatch`, 159 `solver_equation_mismatch`, and one
`undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 0.62%, occur only at step 5187,
and peak transiently at 15.6%; none survives into the 12,800 saved rows. The
saved rows contain no truncations. Mismatch KL stays at most 0.0013 and ends at
zero. Gradient norm stays at most 0.2298 and ends at 0.0589. No NaN, OOM, NCCL
failure, or persistent rollout failure appears. The step-5200 trainer and
orchestrator checkpoints, eight distributed trainer shards, stable inference
weights, 512 training rows, and all 3,000 evaluation rows are complete.

Step 5225 reaches 24.95% on OP11–20, 12.42% on OP15–20, and 3.60% on
OP21–25. OP20 scores 7.00% on both released and executable strict, 2.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint means remain 7.25% for both
released and executable strict, 2.516 points above the SFT result. OP21, OP22,
OP23, OP24, and OP25 score 6.5%, 6.5%, 4.0%, 0.5%, and 0.5%, respectively.
All executable OP20–25 positives repeat previously solved problems, so
cumulative breadth remains 43, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 535/3,000 trajectories pass released strict and
532/3,000 pass the executable grader, for 99.44% precision. All three rejected
rows contain genuine solver or undefined-symbol errors; no pure-extra-node
discrepancy appears. Issue-code counts are three `solver_equation_mismatch`
and one `undefined_symbol`, with overlap. Evaluation has no rollout errors,
three truncations, and mixes adjacent asynchronous policy versions 5224 and
5225.

The preceding train window has released-strict reward 0.4716 and executable
strict success 0.4539, for 96.26% precision among 6,036 released passes. No
pure-extra-node rejection appears, and all 226 executable rejections are
genuine. Prompt 599 contributes 101 by changing the correct `18*x + 4` total
to `17*x + 4`, then retaining answer 4 despite displaying `76 / 17`. Prompt
392 contributes 47 by changing `11*x + 9` to `11*x + 15`, then retaining
answer 1. Prompt 992 contributes 32 by changing the correct `13*x + 32` total
to `15*x + 32`, then retaining answer 2. These three clusters account for
180/226 defects. Issue-code counts are 206 `solver_equation_mismatch`, 138
`equation_mismatch`, and two `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 1.24%, occur only at step 5222,
and peak transiently at 30.9%; none survives into the 12,800 saved rows. The
saved rows contain no truncations. Mismatch KL stays at most 0.0012 and ends at
0.0001. Gradient norm stays at most 0.4124 and ends at 0.0339. No NaN, OOM,
NCCL failure, or persistent rollout failure appears. The step-5225 trainer and
orchestrator checkpoints, eight distributed trainer shards, stable inference
weights, 512 training rows, and all 3,000 evaluation rows are complete.

Step 5250 reaches 26.45% on OP11–20, 14.08% on OP15–20, and 4.00% on
OP21–25. OP20 scores 7.50% on released strict and 7.00% on executable strict.
The rolling last-ten-checkpoint estimates are 7.40% released and 7.35%
executable strict, respectively 2.666 and 2.616 percentage points above the
matched strict-filter OP20 SFT checkpoint's 4.734% pass@1. OP21, OP22, OP23,
OP24, and OP25 score 8.0%, 7.5%, 2.5%, 0.5%, and 1.5%, respectively. All
executable OP20–25 positives repeat previously solved problems, so cumulative
breadth remains 43, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 569/3,000 trajectories pass released strict and
558/3,000 pass the executable grader, for 98.07% raw precision. One released
OP13 rejection, index 54, is semantically valid: it correctly derives the
irrelevant Festival de Clairmont total of 18, which the executable grader
classifies as an unexpected node. Counting that benign extra fact gives
559/569 semantic precision, or 98.24%, and leaves ten genuine defects. The
adjusted issue counts are six `equation_mismatch` and eight
`solver_equation_mismatch`, with overlap. Evaluation has no rollout errors,
two truncations, and mixes adjacent asynchronous policy versions 5249 and
5250.

The preceding train window has released-strict reward 0.3908 and executable
strict success 0.3755, for 96.10% precision among 5,002 released passes. All
195 executable rejections are genuine. Prompt 511 contributes 111 by changing
the correct Ruby total `39*x + 12` to `39*x + 24`, then retaining answer 1.
Prompt 263 contributes 55 by changing the correct Verdi total `5*x + 12` to
`9*x + 12`, then retaining answer 2. Prompt 846 contributes 11 by changing the
correct Northwood total `13*x + 45` to `13*x + 51`, then retaining answer 3.
These three clusters account for 177/195 defects. Issue-code counts are 193
`equation_mismatch` and 156 `solver_equation_mismatch`, with overlap.

Logged off-policy cancellation errors average 1.00%, occur only at step 5242,
and peak transiently at 25.0%; none survives into the 12,800 saved rows. The
saved rows contain one truncation. Mismatch KL stays at most 0.0004 and ends at
zero. Gradient norm stays at most 0.1777 and ends at 0.0985. No NaN, OOM, NCCL
failure, or persistent rollout failure appears. The step-5250 trainer and
orchestrator checkpoints, eight distributed trainer shards, seven stable
inference-weight files, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 5275 reaches 25.95% on OP11–20, 13.92% on OP15–20, and 4.80% on
OP21–25. OP20 scores 7.00% on both released and executable strict, 2.266
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates are 7.25% released
and 7.20% executable strict, respectively 2.516 and 2.466 points above SFT.
OP21, OP22, OP23, OP24, and OP25 score 9.5%, 8.5%, 5.0%, 0.5%, and 0.5%,
respectively. All executable OP20–25 positives repeat previously solved
problems, so cumulative breadth remains 43, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 567/3,000 trajectories pass released strict and
557/3,000 pass the executable grader, for 98.24% raw precision. Two released
rejections are semantically valid but include correct irrelevant facts: OP13
index 54 derives the Festival de Clairmont total of 18, and OP15 index 120
derives three unrelated animal counts from explicit prompt facts. Counting
them gives 559/567 semantic precision, or 98.59%, and leaves eight genuine
defects. OP14 index 55 incorrectly substitutes Ruby Bay's total for Shoreline
City's total, while OP16 index 50 incorrectly uses South Zoo's bear count to
derive Mayer Aquarium's deer count; their extra nodes are not benign. Adjusted
issue-code counts are four `equation_mismatch`, four
`solver_equation_mismatch`, and two `unexpected_node`, with overlap.
Evaluation has no rollout errors, three truncations, and uses policy version
5274 throughout.

The preceding train window has released-strict reward 0.4147 and executable
strict success 0.4009, for 96.67% precision among 5,308 released passes. All
177 executable rejections are genuine. Prompt 627 contributes 90 by writing
`120 - 8 = 92` instead of 112, then retaining the correct downstream answer
336. Prompt 1191 contributes 19 by changing the correct `2*x + 55` total to
`2*x + 67`, then retaining answer 2. Prompts 31 and 645 contribute 14 each
through compensating arithmetic errors while retaining their correct final
answers. These four clusters account for 137/177 defects. Issue-code counts
are 174 `equation_mismatch`, 52 `solver_equation_mismatch`, and one
`undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 2.72%, occur at steps 5254,
5271, 5272, and 5274, and peak transiently at 20.6%; none survives into the
12,800 saved rows. The saved rows contain three truncations. Mismatch KL stays
at most 0.0002 and ends at zero. Gradient norm stays at most 0.3119 and ends at
0.1338. No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-5275 trainer and orchestrator checkpoints, eight distributed trainer
shards, seven stable inference-weight files, 512 training rows, and all 3,000
evaluation rows are complete.

Step 5300 reaches 26.40% on OP11–20, 13.83% on OP15–20, and 4.50% on
OP21–25. OP20 scores 7.50% on both released and executable strict, 2.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates are 7.10% released
and 7.05% executable strict, respectively 2.366 and 2.316 points above SFT.
OP21, OP22, OP23, OP24, and OP25 score 8.0%, 9.5%, 3.5%, 1.0%, and 0.5%,
respectively. OP20 index 94 is a new executable-strict success and expands
cumulative OP20 breadth from 43 to 44/200 prompts. Manual inspection confirms
the exact dependency graph and arithmetic through Northwood 18, West Sahara
75, and Golden Banana 93. Cumulative OP21–25 breadth remains 46, 39, 26, 13,
and seven prompts.

Across the full evaluation, 573/3,000 trajectories pass released strict and
562/3,000 pass the executable grader, for 98.08% raw precision. OP13 index 54
is the sole semantically valid rejection: it correctly derives the irrelevant
Festival de Clairmont total of 18. Counting it gives 563/573 semantic
precision, or 98.25%, and leaves ten genuine defects. OP16 index 50 again
derives an invalid extra node by using South Zoo's bear count in place of Mayer
Aquarium's bear count. Adjusted issue-code counts are five
`equation_mismatch`, seven `solver_equation_mismatch`, and one
`unexpected_node`, with overlap. Evaluation has no rollout errors, one
truncation, and mixes adjacent asynchronous policy versions 5299 and 5300.

The preceding train window has released-strict reward 0.4997 and executable
strict success 0.4899, for 98.05% precision among 6,396 released passes. All
125 executable rejections are genuine. Prompt 1211 contributes 44 by reversing
`4 - 2` to `2 - 4`, then changing `4 * -2` back to positive 8. Prompt 1697
contributes ten through the compensating claims `46 + 26 = 84` and
`84 + 7 = 79`. Prompt 551 contributes nine through `15 + 108 = 99` followed
by `99 + 8 = 131`, and prompt 386 contributes eight by changing `x + 4` to
`3*x + 2`. These four clusters account for 71/125 defects. The sole
unexpected-node case derives the correct irrelevant value 2 for Bundle
Ranch's blue jay but cites the wrong dependency, so it is not treated as
semantically valid. Issue-code counts are 122 `equation_mismatch`, 23
`solver_equation_mismatch`, one `expression_syntax`, one `undefined_symbol`,
and one `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 0.66%, occur only at step 5294,
and peak transiently at 16.4%; none survives into the 12,800 saved rows. The
saved rows contain one truncation. Mismatch KL stays at most 0.0003 and ends at
0.0001. Gradient norm stays at most 0.3554 and ends at 0.0613. No NaN, OOM,
NCCL failure, or persistent rollout failure appears. The step-5300 trainer and
orchestrator checkpoints, eight distributed trainer shards, seven stable
inference-weight files, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 5325 reaches 24.75% on OP11–20, 13.83% on OP15–20, and 4.10% on
OP21–25. OP20 scores 7.50% on both released and executable strict, 2.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates are 7.25% released
and 7.20% executable strict, respectively 2.516 and 2.466 points above SFT.
OP21, OP22, OP23, OP24, and OP25 score 8.0%, 7.5%, 4.0%, 0.5%, and 0.5%,
respectively. No new executable OP20–25 prompt appears, so cumulative breadth
remains 44, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 536/3,000 trajectories pass released strict and
525/3,000 pass the executable grader, for 97.95% raw precision. OP13 index 54
is the sole semantically valid rejection and again correctly derives the
irrelevant Festival de Clairmont total of 18. Counting it gives 526/536
semantic precision, or 98.13%, and leaves ten genuine defects. OP13 index 32
invents a Riverton culinarian-school node; OP14 index 55 and OP16 index 50 use
the previously identified wrong dependencies in their extra nodes. Adjusted
issue-code counts are four `equation_mismatch`, four
`solver_equation_mismatch`, and three `unexpected_node`, with overlap.
Evaluation has no rollout errors or truncations and mixes adjacent asynchronous
policy versions 5324 and 5325.

The preceding train window has released-strict reward 0.4859 and executable
strict success 0.4659, for 95.90% precision among 6,219 released passes. All
255 executable rejections are genuine. Prompt 597 contributes 70 by changing
the correct total `8*x + 12` to `14*x + 12`, then retaining answer 1. Prompt
1353 contributes 69 through the compensating claims `64 + 24 = 112` and
`112 + 40 = 128`. Prompt 1219 contributes 63 through `16 + 84 = 112`
followed by `112 + 2 = 102`, and prompt 1364 contributes 13 through another
pair of compensating sum errors. These four clusters account for 215/255
defects. Issue-code counts are 249 `equation_mismatch`, 84
`solver_equation_mismatch`, and four `undefined_symbol`, with overlap.

Logged off-policy cancellation errors average 2.17%, occur at steps 5301,
5305, and 5318, and peak transiently at 18.6%; none survives into the 12,800
saved rows. The saved rows contain two truncations. Mismatch KL stays at most
0.0010 and ends at 0.0001. Gradient norm stays at most 0.3684 and ends at
0.1014. No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-5325 trainer and orchestrator checkpoints, eight distributed trainer
shards, seven stable inference-weight files, 512 training rows, and all 3,000
evaluation rows are complete.

Step 5350 reaches 25.30% on OP11–20, 13.92% on OP15–20, and 4.40% on
OP21–25. OP20 scores 8.50% on both released and executable strict, 3.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates reach 7.55% released
and 7.50% executable strict, respectively 2.816 and 2.766 points above SFT.
OP21, OP22, OP23, OP24, and OP25 score 8.5%, 8.5%, 4.0%, 1.0%, and 0.0%,
respectively. No new executable OP20–25 prompt appears, so cumulative breadth
remains 44, 46, 39, 26, 13, and seven prompts.

Across the full evaluation, 550/3,000 trajectories pass released strict and
539/3,000 pass the executable grader, for 98.00% raw precision. OP13 index 54
is the sole semantically valid rejection and correctly derives the irrelevant
Festival de Clairmont total of 18. Counting it gives 540/550 semantic
precision, or 98.18%, and leaves ten genuine defects. OP13 index 74 assigns
Evervale City's private-middle-school count as 5 rather than the prompt's 3,
and OP16 index 50 again derives Mayer Aquarium's deer from the wrong bear
count. Adjusted issue-code counts are four `equation_mismatch`, six
`solver_equation_mismatch`, two `unexpected_node`, and one `undefined_symbol`,
with overlap. Evaluation has no rollout errors, one truncation, and mixes
adjacent asynchronous policy versions 5349 and 5350.

The preceding train window has released-strict reward 0.3991 and executable
strict success 0.3858, for 96.65% precision among 5,109 released passes. All
171 executable rejections are genuine. Prompt 1087 contributes 50 through the
compensating claims `80 + 24 = 116` and `116 + 12 = 116`. Prompt 903
contributes 32 by changing the correct total `9*x + 5` to `5*x + 5`, then
retaining answer 3. Prompt 1553 contributes 20 through `27 + 48 = 99`
followed by `99 + 24 = 99`, and prompt 372 contributes 15 by changing the
correct total `5*x + 3` to `7*x + 3` before retaining answer 2. These four
clusters account for 117/171 defects. The sole unexpected-node row assigns a
Golden Banana calm-road count from the wrong dependency and is a genuine
defect. Issue-code counts are 167 `equation_mismatch`, 77
`solver_equation_mismatch`, and one `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 2.12%, occur at steps 5328,
5330, and 5343, and peak transiently at 21.9%; none survives into the 12,800
saved rows. The saved rows contain no truncations. Mismatch KL briefly reaches
0.0037 at step 5333 and ends at 0.0007. Gradient norm peaks at 0.4868 on the
same step and ends at 0.0416; neither excursion persists. No NaN, OOM, NCCL
failure, or persistent rollout failure appears. The step-5350 trainer and
orchestrator checkpoints, eight distributed trainer shards, seven stable
inference-weight files, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 5375 reaches 24.10% on OP11–20, 13.08% on OP15–20, and a new run high of
5.10% on OP21–25. OP20 scores 6.00% on both released and executable strict,
1.266 percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates remain 7.55% released
and 7.50% executable strict, respectively 2.816 and 2.766 points above SFT.
OP21, OP22, OP23, OP24, and OP25 score 9.5%, 10.5%, 3.5%, 1.0%, and 1.0%,
respectively. OP23 index 136 is a new executable-strict success and expands
cumulative OP23 breadth from 26 to 27/200 prompts. Manual inspection confirms
the exact dependency graph and arithmetic through Beverly Forest 11, Cedar
Valley 31, and Maple Creek 59. Cumulative OP20–22 and OP24–25 breadth remains
44, 46, 39, 13, and seven prompts.

Across the full evaluation, 533/3,000 trajectories pass released strict and
523/3,000 pass the executable grader, for 98.12% raw precision. OP17 index 172
is the sole semantically valid rejection: it correctly derives the irrelevant
Cinéma de Montreval calm-road count of 5 from an explicit prompt relation.
Counting it gives 524/533 semantic precision, or 98.31%, and leaves nine
genuine defects. OP16 index 50 again derives Mayer Aquarium's deer from the
wrong bear count. Adjusted issue-code counts are four `equation_mismatch`,
seven `solver_equation_mismatch`, and one `unexpected_node`, with overlap.
Evaluation has no rollout errors, two truncations, and mixes adjacent
asynchronous policy versions 5374 and 5375.

The preceding train window has released-strict reward 0.3690 and executable
strict success 0.3473, for 94.14% raw precision among 4,723 released passes.
One rejected row correctly derives the irrelevant prompt-stated Ruby Bay
regional-medical-school count of 43. Counting it gives 4,447 semantically
valid passes, 94.16% semantic precision, and 276 genuine defects. Prompt 277
contributes 120 by deriving Clearwater Bay's regional-medical-school count as
9 rather than the prompt-implied 15. Prompt 1168 contributes 96 by changing
the correct total `20*x + 14` to `19*x + 14`, then retaining answer 2. Prompts
318 and 1305 contribute 14 each by changing the correct totals `3*x + 4` and
`16*x + 31` while retaining the correct answers. These four clusters account
for 244/276 genuine defects. Adjusted issue-code counts are 117
`solver_equation_mismatch`, 120 `unexpected_node`, 60 `equation_mismatch`, and
one each of `definition_dependency_mismatch`, `definition_value_mismatch`,
and `unsupported_expression`, with overlap.

Logged off-policy cancellation errors average 0.50%, occur only at step 5374,
and peak transiently at 12.4%; none survives into the 12,800 saved rows. The
saved rows contain one truncation. Mismatch KL stays at most 0.0004 and ends at
0.0002. Gradient norm stays at most 0.1541 and ends at 0.0766. No NaN, OOM,
NCCL failure, or persistent rollout failure appears. The step-5375 trainer and
orchestrator checkpoints, eight distributed trainer shards, seven stable
inference-weight files, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 5400 sets a new OP11–20 run high of 28.00%, with OP15–20 at 15.00% and
OP21–25 at 4.30%. OP20 scores 8.50% released strict and 8.00% executable
strict, respectively 3.766 and 3.266 percentage points above the matched
strict-filter OP20 SFT checkpoint's 4.734% pass@1. The rolling
last-ten-checkpoint estimates are 7.50% released and 7.40% executable strict,
respectively 2.766 and 2.666 points above SFT. OP21, OP22, OP23, OP24, and
OP25 score 8.5%, 7.0%, 4.5%, 1.0%, and 0.5%, respectively. No new executable
OP20–25 prompt appears, so cumulative breadth remains 44, 46, 39, 27, 13, and
seven prompts.

Across the full evaluation, 603/3,000 trajectories pass released strict and
592/3,000 pass the executable grader, for 98.18% precision. All eleven
rejections are genuine: OP13 index 32 invents a Riverton culinarian-school
node, OP16 index 50 again derives Mayer Aquarium's deer from the wrong bear
count, and OP20 index 133 contains arithmetic and solver inconsistencies.
Issue-code counts are five `equation_mismatch`, nine
`solver_equation_mismatch`, and two `unexpected_node`, with overlap.
Evaluation has no rollout errors, one truncation, and mixes adjacent
asynchronous policy versions 5399 and 5400.

The preceding train window has released-strict reward 0.5613 and executable
strict success 0.5427, for 96.67% precision among 7,185 released passes. All
239 executable rejections are genuine. Prompt 706 contributes 82 by changing
the correct total `48*x + 15` to `36*x + 15`, while retaining answer 1.
Prompt 698 contributes 68 by deriving Hawkesbury's private-middle-school count
as 5 rather than the prompt-implied 6. Prompt 301 contributes 16 by using an
undefined self-reference and constructing the wrong symbolic total. These
three clusters account for 166/239 defects. The other three unexpected-node
clusters are also invalid: they invent a category or derive a prompt-stated
fact from the wrong values. Issue-code counts are 139 `equation_mismatch`,
100 `solver_equation_mismatch`, 71 `unexpected_node`, and 15
`undefined_symbol`, with overlap.

The window has no logged rollout errors, and all 12,800 saved rows are free of
errors and truncations. Mismatch KL stays at most 0.0003 and ends at 0.0001.
Gradient norm stays at most 0.3844 and ends at 0.0742. No NaN, OOM, NCCL
failure, or persistent rollout failure appears. The step-5400 trainer and
orchestrator checkpoints, eight distributed trainer shards, seven stable
inference-weight files, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 5425 raises the OP11–20 run high slightly to 28.10%, with OP15–20 at
15.17% and OP21–25 at 4.20%. OP20 scores 9.00% under both released and
executable strict grading. The rolling last-ten-checkpoint estimates are
7.60% released and 7.50% executable strict, respectively 2.866 and 2.766
percentage points above the matched strict-filter OP20 SFT checkpoint's
4.734% pass@1. OP21, OP22, OP23, OP24, and OP25 score 8.5%, 6.5%, 4.5%,
1.5%, and 0.0%, respectively. No new executable OP20–25 prompt appears, so
cumulative breadth remains 44, 46, 39, 27, 13, and seven prompts.

Across the full evaluation, 604/3,000 trajectories pass released strict and
595/3,000 pass the executable grader, for 98.51% raw precision. OP13 index 54
is a semantically valid rejection: it derives an irrelevant Festival de
Clairmont total of 18 using an explicit prompt relation. Counting it gives
596/604 semantic precision, or 98.68%, and leaves eight genuine defects.
OP14 index 55 substitutes Ruby Bay's total for Shoreline's total, and OP16
index 50 again uses South Zoo's bear count for Mayer Aquarium's deer count.
Adjusted issue-code counts are one `equation_mismatch`, six
`solver_equation_mismatch`, and two `unexpected_node`, with overlap.
Evaluation has no rollout errors, three truncations, and mixes adjacent
asynchronous policy versions 5424 and 5425.

The preceding train window has released-strict reward 0.4018 and executable
strict success 0.3888, for 96.75% raw precision among 5,143 released passes.
One rejected row correctly derives the irrelevant prompt-stated Brightford
regional-medical-school count of 43. Counting it gives 4,977 semantically
valid passes, 96.77% semantic precision, and 166 genuine defects. Prompt 378
contributes 49 by changing the correct total `9*x + 36` to `13*x + 36` and
then falsely solving it to answer 3. Prompt 1191 contributes 43 by changing
the correct total `2*x + 55` to `2*x + 67` while retaining answer 2. Prompt
1126 contributes 42 by changing the correct total `25*x + 8` to `29*x + 8`
and then changing the residual from 100 to 116 to force answer 4. These three
clusters account for 134/166 genuine defects. A singleton unexpected-node
failure derives Hamilton Zoo's blue-jay count from the wrong dependencies but
reaches the right value by coincidence. Adjusted issue-code counts are 147
each of `equation_mismatch` and `solver_equation_mismatch`, one
`undefined_symbol`, and one `unexpected_node`, with overlap.

Logged off-policy cancellation errors average 1.36%, occur only at step 5410,
and peak transiently at 33.9%; none survives into the 12,800 saved rows. The
saved rows contain no truncations. Inference paused for about 104 seconds
after step 5421 while every scheduler process and HTTP health check remained
healthy, then resumed without intervention; the step-5425 evaluation therefore
took about 1 minute 58 seconds. Mismatch KL stays at most 0.0002 and ends at
0.0000. Gradient norm stays at most 0.1520 and ends at 0.0251. No NaN, OOM,
NCCL failure, or persistent rollout failure appears. The step-5425 trainer and
orchestrator checkpoints, eight distributed trainer shards, seven stable
inference-weight files, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 5450 falls to 22.55% over OP11–20, 13.17% over OP15–20, and 3.50% over
OP21–25 after the step-5425 high. OP20 scores 7.50% under both released and
executable strict grading, still 2.766 percentage points above the matched
strict-filter SFT checkpoint's 4.734% pass@1. The rolling last-ten-checkpoint
estimates remain 7.60% released and 7.50% executable strict, respectively
2.866 and 2.766 points above SFT. OP21, OP22, OP23, OP24, and OP25 score
8.0%, 5.0%, 3.0%, 1.0%, and 0.5%, respectively. No new executable OP20–25
prompt appears, so cumulative breadth remains 44, 46, 39, 27, 13, and seven
prompts.

Across the full evaluation, 486/3,000 trajectories pass released strict and
470/3,000 pass the executable grader, for 96.71% raw precision. OP11 index
152 is a semantically valid rejection: it correctly derives the irrelevant
prompt-stated Bundle Ranch crow count of 6. Counting it gives 471/486 semantic
precision, or 96.91%, and leaves 15 genuine defects. OP16 index 50 again
derives Mayer Aquarium's deer from South Zoo's bear count rather than Mayer
Aquarium's bear count. Adjusted issue-code counts are twelve
`solver_equation_mismatch`, six `equation_mismatch`, two `undefined_symbol`,
and one `unexpected_node`, with overlap. Direct executable regrading exactly
matches every saved metric. Evaluation has no rollout errors, one truncation,
and mixes asynchronous policy versions 5449, 5450, and 5451.

The preceding train window has released-strict reward 0.3888 and executable
strict success 0.3776, for 97.11% raw precision among 4,977 released passes.
All 117 unexpected-node rejections come from prompt 154, where the model
correctly derives the irrelevant prompt-stated Oakridge Riverside bear count
of 24. Counting them gives 4,950 semantically valid passes, 99.46% semantic
precision, and 27 genuine defects. Prompt 1301 contributes five by changing
the solver residual in `26*x + 7 = 85` from 78 to 72 and then claiming
`72 / 26 = 3`. Prompt 274 contributes four through compensating false
equalities `24 + 56 = 92` and `92 + 3 = 83`. Four other two-trajectory
clusters contain stale-variable, equation, or forced-solver arithmetic. These
six clusters account for 17/27 genuine defects. After removing the benign
extra node, issue-code counts are 21 `equation_mismatch` and twelve
`solver_equation_mismatch`, with overlap. Direct executable regrading again
matches every saved metric.

Logged rollout-error percentages average 2.68% and peak at 58.8%; the two
nonzero batches at steps 5446 and 5450 reflect cancellation of trajectories
past the 16-step off-policy limit. An isolated all-dropped batch at step 5442
also clears on the next attempt. None of these errors survives into the 12,800
saved rows, which contain one truncation. Mismatch KL stays at most 0.0013 and
ends at 0.0000. Gradient norm stays at most 0.6963 and ends at 0.0534. No NaN,
OOM, NCCL failure, or persistent rollout failure appears. The step-5450
trainer and orchestrator checkpoints, eight distributed trainer shards, seven
stable inference-weight files, 512 training rows, and all 3,000 evaluation
rows are complete.

Step 5475 scores 22.05% over OP11–20, 11.92% over OP15–20, and 4.40% over
OP21–25. OP20 scores 6.00% under both released and executable strict grading,
1.266 percentage points above the matched strict-filter SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates are 7.50% released
and 7.40% executable strict, respectively 2.766 and 2.666 points above SFT.
OP21, OP22, OP23, OP24, and OP25 score 7.0%, 8.5%, 4.0%, 1.5%, and 1.0%,
respectively. No new executable OP20–25 prompt appears, so cumulative breadth
remains 44, 46, 39, 27, 13, and seven prompts.

Across the full evaluation, 485/3,000 trajectories pass released strict and
469/3,000 pass the executable grader, for 96.70% raw precision. OP11 index
152 correctly derives the irrelevant prompt-stated Bundle Ranch crow count of
6, and OP13 index 54 correctly derives the irrelevant Festival de Clairmont
total of 18. Counting these semantically valid rejections gives 471/485
semantic precision, or 97.11%, and leaves 14 genuine defects. OP16 index 50
again derives Mayer Aquarium's deer from South Zoo's bear count. Adjusted
issue-code counts are ten `solver_equation_mismatch`, seven
`equation_mismatch`, three `undefined_symbol`, and one `unexpected_node`, with
overlap. Direct executable regrading exactly matches every saved metric.
Evaluation has no rollout errors or truncations and mixes adjacent asynchronous
policy versions 5474 and 5475.

The preceding train window has released-strict reward 0.3974 and executable
strict success 0.3723, for 93.67% raw precision among 5,087 released passes.
Thirty-two rejected rows correctly derive the irrelevant prompt-stated
Hawkesbury public-highschool count of 36, and three correctly derive the
irrelevant Clearwater Bay private-middle-school expression `x + 4`. Counting
them gives 4,800 semantically valid passes, 94.36% semantic precision, and 287
genuine defects. Prompt 599 contributes 119 by omitting `x` from the animal
total, writing `17*x + 4` instead of `18*x + 4`, and then forcing answer 4.
Prompt 273 contributes 59 through an incorrect duplicate dependency and an
invented Evervale or Glenfield total. Prompt 321 contributes 55 by changing
the correct total `15*x + 38` to `18*x + 35` and forcing answer 2. Prompt 1658
contributes 19 by changing `25*x + 8` to `19*x + 8` and forcing answer 2.
These four clusters account for 252/287 genuine defects. Adjusted issue-code
counts are 199 `solver_equation_mismatch`, 84 `equation_mismatch`, 59
`definition_dependency_mismatch`, 58 `unexpected_node`, two
`undefined_symbol`, and one `expression_syntax`, with overlap. Direct
executable regrading again matches every saved metric.

Logged rollout-error percentages average 16.88%, occur in 14/25 batches, and
peak at 68.0% while a stale off-policy backlog is cancelled. No error survives
into the 12,800 saved rows, which contain two truncations, and subsequent steps
return to zero logged error. Mismatch KL spikes transiently to 0.0121 and ends
at 0.0000. Gradient norm stays at most 0.2611 and ends at 0.0721. No NaN, OOM,
NCCL failure, or persistent rollout failure appears. The step-5475 trainer and
orchestrator checkpoints, eight distributed trainer shards, seven stable
inference-weight files, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 5500 rebounds to 25.70% over OP11–20, with OP15–20 at 13.33% and
OP21–25 at 4.30%. OP20 scores 9.00% under both released and executable strict
grading, 4.266 percentage points above the matched strict-filter SFT
checkpoint's 4.734% pass@1. The rolling last-ten-checkpoint estimates rise to
7.65% released and 7.60% executable strict, respectively 2.916 and 2.866
points above SFT. OP21, OP22, OP23, OP24, and OP25 score 9.0%, 6.0%, 5.0%,
1.5%, and 0.0%, respectively. No new executable OP20–25 prompt appears, so
cumulative breadth remains 44, 46, 39, 27, 13, and seven prompts.

Across the full evaluation, 557/3,000 trajectories pass released strict and
551/3,000 pass the executable grader, for 98.92% precision. All six rejections
are genuine arithmetic defects; issue-code counts are six
`solver_equation_mismatch` and three `equation_mismatch`, with overlap. Direct
executable regrading exactly matches every saved metric. Evaluation has no
rollout errors, two truncations, and mixes adjacent asynchronous policy
versions 5499 and 5500.

The preceding train window has released-strict reward 0.4224 and executable
strict success 0.4060, for 96.12% raw precision among 5,407 released passes.
One rejected row correctly derives the irrelevant prompt-stated Brightford
elementary-school count of 27. Counting it gives 5,198 semantically valid
passes, 96.13% semantic precision, and 209 genuine defects. Prompt 515
contributes 67 by duplicating a `2*x` culinarian-school node, writing `44*x`
instead of the correct `38*x`, and forcing answer 3. Prompt 235 contributes 67
by changing `21*x + 4` to `23*x + 4` and forcing answer 2. Prompt 371
contributes 25 by adding an undefined symbol to change the correct `10*x`
total to `12*x`, then forcing answer 3. Prompts 1178 and 1006 contribute 14
and eleven through corrupted and compensating arithmetic, respectively. These
five clusters account for 184/209 genuine defects. The other unexpected node
uses an undefined symbol and the wrong dependency to derive Jefferson Circus's
blue-jay count. Adjusted issue-code counts are 185
`solver_equation_mismatch`, 162 `equation_mismatch`, four `undefined_symbol`,
and one `unexpected_node`, with overlap. Direct executable regrading again
matches every saved metric.

Logged rollout error is zero in 24/25 batches and 16.8% at step 5495 while
stale off-policy trajectories are cancelled, for a 0.67% window average. No
error or truncation survives into the 12,800 saved rows. Mismatch KL spikes
transiently to 0.0091 and ends at 0.0000. Gradient norm stays at most 0.5731
and ends at 0.0210. No NaN, OOM, NCCL failure, or persistent rollout failure
appears. The step-5500 trainer and orchestrator checkpoints, eight distributed
trainer shards, seven stable inference-weight files, 512 training rows, and
all 3,000 evaluation rows are complete.

Step 5525 reaches 26.45% over OP11–20, with OP15–20 at 13.00% and OP21–25 at
4.50%. OP20 scores 7.50% under both released and executable strict grading,
2.766 percentage points above the matched strict-filter SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates rise to 7.70%
released and 7.65% executable strict, respectively 2.966 and 2.916 points
above SFT. OP21, OP22, OP23, OP24, and OP25 score 8.0%, 7.0%, 5.5%, 1.5%,
and 0.5%, respectively. No new executable OP20–25 prompt appears, so
cumulative breadth remains 44, 46, 39, 27, 13, and seven prompts.

Across the full evaluation, 574/3,000 trajectories pass released strict and
563/3,000 pass the executable grader, for 98.08% precision. All eleven
rejections are genuine arithmetic or dependency defects; OP16 index 50 again
derives Mayer Aquarium's deer from South Zoo's bear count. Issue-code counts
are eight `solver_equation_mismatch`, seven `equation_mismatch`, and one
`unexpected_node`, with overlap. Direct executable regrading exactly matches
every saved metric. Evaluation has no rollout errors or truncations and mixes
adjacent asynchronous policy versions 5524 and 5525.

The preceding train window has released-strict reward 0.3545 and executable
strict success 0.3453, for 97.42% precision among 4,537 released passes. All
117 executable rejections are genuine. Prompt 570 contributes 54 by changing
the correct sum `72 + 16 = 88` to 76 and then forcing answer 3. Prompt 464
contributes 13 by changing `15*x + 8` to `19*x + 8` and forcing answer 3.
Prompt 1323 contributes twelve by changing `43*x + 16` to `31*x + 28`.
Prompt 156 contributes eight through invented or incorrectly derived animal
nodes, and prompt 1151 contributes seven through compensating false
equalities. These five clusters account for 94/117 genuine defects. Issue-code
counts are 104 `equation_mismatch`, 89 `solver_equation_mismatch`, and nine
`unexpected_node`, with overlap. Direct executable regrading again matches
every saved metric.

Logged rollout-error percentages are nonzero only at steps 5513 and 5514,
average 1.05%, and peak at 22.2% while stale off-policy trajectories are
cancelled. No error or truncation survives into the 12,800 saved rows.
Mismatch KL spikes transiently to 0.0115 and ends at 0.0000. Gradient norm
spikes transiently to 1.2290 and ends at 0.0219. No NaN, OOM, NCCL failure, or
persistent rollout failure appears. The step-5525 trainer and orchestrator
checkpoints, eight distributed trainer shards, seven stable inference-weight
files, 512 training rows, and all 3,000 evaluation rows are complete.

Step 5550 reaches 27.45% over OP11–20, with OP15–20 at 14.83% and OP21–25 at
5.20%. OP20 scores 8.50% under both released and executable strict grading,
3.766 percentage points above the matched strict-filter SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates rise to 7.80%
released and 7.75% executable strict, respectively 3.066 and 3.016 points
above SFT. OP21, OP22, OP23, OP24, and OP25 score 10.0%, 10.0%, 3.5%, 2.0%,
and 0.5%, respectively. New executable successes on OP20 index 15 and OP22
index 161 expand cumulative breadth to 45, 46, 40, 27, 13, and seven prompts
for OP20–25. Manual inspection confirms both new traces follow the exact
dependency graph and arithmetic to answers 53 and 34.

Across the full evaluation, 601/3,000 trajectories pass released strict and
589/3,000 pass the executable grader, for 98.00% raw precision. Two rejected
rows correctly derive irrelevant prompt-stated nodes: Beverly Forest's owl
count of 6 and Oakridge Riverside's bear count of 13. Counting them gives
591/601 semantic precision, or 98.34%, and leaves ten genuine defects. OP16
index 50 again derives Mayer Aquarium's deer from South Zoo's bear count, and
OP16 index 97 invents a Maple Creek bear count. Adjusted issue-code counts are
six `solver_equation_mismatch`, four `equation_mismatch`, two
`unexpected_node`, and one `undefined_symbol`, with overlap. Direct executable
regrading exactly matches every saved metric. Evaluation has no rollout
errors, one truncation, and mixes adjacent asynchronous policy versions 5549
and 5550.

The preceding train window has released-strict reward 0.3966 and executable
strict success 0.3770, for 95.06% raw precision among 5,076 released passes.
All 125 unexpected-node rejections on prompt 765 correctly derive an
irrelevant prompt-stated crow node. Counting them gives 4,950 semantically
valid passes, 97.52% semantic precision, and 126 genuine defects. Prompt 1304
contributes 66 through an inconsistent first equality and a forced solver.
Prompt 662 contributes 29 by changing `64 + 63 = 127` to 148 and forcing
answer 4. Prompt 505 contributes five by dropping 12 from `x + 66`; prompts
753 and 1057 contribute four each through compensating or symbolic arithmetic
errors. These five clusters account for 108/126 genuine defects. Adjusted
issue-code counts are 124 `equation_mismatch`, 106
`solver_equation_mismatch`, and two `undefined_symbol`, with overlap. Direct
executable regrading again matches every saved metric.

Logged rollout error is zero in 24/25 batches and 17.3% at step 5531 while
stale off-policy trajectories are cancelled, for a 0.69% window average. No
error or truncation survives into the 12,800 saved rows. Mismatch KL stays at
most 0.0040 and ends at 0.0040. Gradient norm stays at most 0.5175 and ends at
0.0791. No NaN, OOM, NCCL failure, or persistent rollout failure appears. The
step-5550 trainer and orchestrator checkpoints, eight distributed trainer
shards, seven stable inference-weight files, 512 training rows, and all 3,000
evaluation rows are complete.

Step 5575 scores 26.10% over OP11–20, with OP15–20 at 14.83% and OP21–25 at
5.10%. OP20 reaches 9.50% under both released and executable strict grading,
4.766 percentage points above the matched strict-filter SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates reach 8.00% released
and 7.95% executable strict, respectively 3.266 and 3.216 points above SFT.
OP21, OP22, OP23, OP24, and OP25 score 9.0%, 9.5%, 5.5%, 1.0%, and 0.5%,
respectively. A new executable success on OP20 index 58 expands cumulative
OP20–25 breadth to 46, 46, 40, 27, 13, and seven prompts. Manual inspection
confirms the new trace follows the exact dependency graph and arithmetic to
answer 73.

Across the full evaluation, 573/3,000 trajectories pass released strict and
561/3,000 pass the executable grader, for 97.91% precision. All twelve
rejections are genuinely problematic. OP13 index 74 includes several correct
irrelevant nodes but also assigns Evervale City's private-middle-school count
from the wrong dependency; OP16 index 50 again derives Mayer Aquarium's deer
from South Zoo's bear count. Issue-code counts are eight
`solver_equation_mismatch`, six `equation_mismatch`, and two
`unexpected_node`, with overlap. Direct executable regrading exactly matches
every saved metric. Evaluation has no rollout errors, two truncations, and
mixes adjacent asynchronous policy versions 5574 and 5575.

The preceding train window has released-strict reward 0.4129 and executable
strict success 0.3873, for 93.79% precision among 5,285 released passes. All
328 executable rejections are genuine. Prompt 62 contributes 117 by changing
the correct total `20 - x` to `20 - 2*x` and forcing answer 3. Prompt 1082
contributes 88 by assigning Evervale City's culinarian-school count as 5
instead of the prompt-implied Westhaven total of 21. Prompt 312 contributes 45
by changing `15*x + 32` to `17*x + 32`; prompt 973 contributes 31 by forcing
answer 3 despite `8*x + 4 = 30`; and prompt 513 contributes nine by changing
`14*x + 24` to `20*x + 24`. These five clusters account for 290/328 genuine
defects. Issue-code counts are 229 `solver_equation_mismatch`, 227
`equation_mismatch`, 89 `unexpected_node`, and five `undefined_symbol`, with
overlap. Direct executable regrading again matches every saved metric.

Logged rollout-error percentages are nonzero at three steps, average 2.11%,
and peak at 19.5% while stale off-policy trajectories are cancelled. No error
survives into the 12,800 saved rows, which contain two truncations. Mismatch KL
stays at most 0.0046 and ends at 0.0003. Gradient norm spikes transiently to
1.5189 and ends at 0.1831 without a loss or reward instability. No NaN, OOM,
NCCL failure, or persistent rollout failure appears. The step-5575 trainer and
orchestrator checkpoints, eight distributed trainer shards, seven stable
inference-weight files, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 5600 scores 23.50% over OP11–20, with OP15–20 at 13.00% and OP21–25 at
4.80%. OP20 remains 9.50% under both released and executable strict grading,
4.766 percentage points above the matched strict-filter SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates reach 8.10% released
and 8.05% executable strict, respectively 3.366 and 3.316 points above SFT.
OP21, OP22, OP23, OP24, and OP25 score 10.0%, 9.0%, 3.0%, 1.0%, and 1.0%,
respectively. No new executable OP20–25 prompt appears, so cumulative breadth
remains 46, 46, 40, 27, 13, and seven prompts.

Across the full evaluation, 518/3,000 trajectories pass released strict and
502/3,000 pass the executable grader, for 96.91% raw precision. OP13 index 54
correctly derives the irrelevant Festival de Clairmont total of 18, and OP16
index 50 correctly derives the irrelevant South Zoo total of 44. Counting
these semantically valid rejections gives 504/518 semantic precision, or
97.30%, and leaves 14 genuine defects. Adjusted issue-code counts are thirteen
`solver_equation_mismatch` and six `equation_mismatch`, with overlap. Direct
executable regrading exactly matches every saved metric. Evaluation has no
rollout errors or truncations and mixes adjacent asynchronous policy versions
5599 and 5600.

The preceding train window has released-strict reward 0.4438 and executable
strict success 0.4106, for 92.54% raw precision among 5,680 released passes.
Four rejected rows correctly derive the irrelevant prompt-stated South Zoo
deer count of 4. Counting them gives 5,260 semantically valid passes, 92.61%
semantic precision, and 420 genuine defects. Prompt 567 contributes 122
through corrupted totals and forced solver steps. Prompt 704 contributes 111
by claiming answer 1 despite `6*x + 13 = 20`. Prompt 580 contributes 81 by
changing `21*x + 12` to `21*x + 18` and forcing answer 3. Prompt 1400
contributes 25 through compensating false equalities, and prompt 572
contributes 23 through multiple inconsistent symbolic totals. These five
clusters account for 362/420 genuine defects. Adjusted issue-code counts are
370 `solver_equation_mismatch`, 211 `equation_mismatch`, eighteen
`unexpected_node`, and seven `undefined_symbol`, with overlap. Direct
executable regrading again matches every saved metric.

Logged rollout error is zero in 24/25 batches and 28.8% at step 5576 while
stale off-policy trajectories are cancelled, for a 1.15% window average. No
error or truncation survives into the 12,800 saved rows. Mismatch KL spikes
transiently to 0.0123 and ends at 0.0037. Gradient norm spikes transiently to
1.7515 and ends at 0.1931 without a loss or reward instability. No NaN, OOM,
NCCL failure, or persistent rollout failure appears. The step-5600 trainer and
orchestrator checkpoints, eight distributed trainer shards, seven stable
inference-weight files, 512 training rows, and all 3,000 evaluation rows are
complete.

Step 5625 scores 27.05% over OP11–20, with OP15–20 at 14.00% and OP21–25 at
4.40%. OP20 reaches 8.00% under both released and executable strict grading,
3.266 percentage points above the matched strict-filter SFT checkpoint's
4.734% pass@1. The rolling last-ten-checkpoint estimates reach 8.30% released
and 8.25% executable strict, respectively 3.566 and 3.516 points above SFT.
OP21, OP22, OP23, OP24, and OP25 score 8.0%, 7.5%, 5.0%, 1.5%, and 0.0%,
respectively. A new executable success on OP21 index 76 expands cumulative
OP20–25 breadth to 46, 47, 40, 27, 13, and seven prompts. Manual inspection
confirms that it follows the exact dependency graph and arithmetic to answer
75.

Across the full evaluation, 585/3,000 trajectories pass released strict and
569/3,000 pass the executable grader, for 97.26% precision. All sixteen
rejections are genuine. OP13 index 54 invents an irrelevant Festival de
Clairmont total of 12 even though its four stated categories sum to 18, and
OP16 index 50 assigns Mayer Aquarium's deer from South Zoo's bear count,
yielding 45 instead of the prompt-implied 7. Issue-code counts are thirteen
`solver_equation_mismatch`, six `equation_mismatch`, two `unexpected_node`,
two `undefined_symbol`, and one `unsupported_expression`, with overlap.
Direct executable regrading exactly matches every saved metric. Evaluation
has no rollout errors, two truncations, and all shards use asynchronous policy
version 5624.

The preceding train window has released-strict reward 0.4181 and executable
strict success 0.3945, for 94.34% precision among 5,352 released passes. All
303 executable rejections are genuine. Prompt 511 contributes 123 by changing
the correct total `39*x + 12` to `33*x + 24` while forcing answer 1. Prompt
304 contributes 120 by adding an extra `x` to the total and forcing answer 3
despite `8*x + 12 = 33`. Prompt 923 contributes fifteen by changing the
solver steps from `22*x = 44` to `22*x = 40` while still answering 2; prompt
583 contributes eleven by changing `x + 58` to `x + 66` while still answering
4; and prompt 330 contributes eight by double-counting a school category and
forcing answer 4. These five clusters account for 277/303 genuine defects.
Issue-code counts are 273 `solver_equation_mismatch` and 164
`equation_mismatch`, with overlap. Direct executable regrading again matches
every saved metric.

Logged rollout-error percentages are nonzero at two steps, average 1.46%, and
peak at 18.3% while stale off-policy trajectories are cancelled. No error
survives into the 12,800 saved rows, which contain one truncation. Mismatch KL
spikes transiently to 0.0159 and ends at 0.0006. Gradient norm stays at most
0.4713 and ends at 0.0124. No NaN, OOM, NCCL failure, or persistent rollout
failure appears. The step-5625 trainer and orchestrator checkpoints, eight
distributed trainer shards, seven stable inference-weight files, 512 training
rows, and all 3,000 evaluation rows are complete.

Step 1000 sets a new OP15–20 aggregate high of 9.08%, above the previous
8.92% at step 850, while OP11–20 remains near its recent range at 20.30%.
OP16 reaches 15.5%; OP15, OP17, OP18, OP19, and OP20 score 24.5%, 9.5%,
2.5%, 1.5%, and 1.0%, respectively. The two OP20 passes repeat known indices
43 and 71 with newly sampled, executable-consistent derivations; they add
replication but no new prompt breadth. OP21–25 returns to zero, again showing
that beyond-training-range success is not yet stable. Across the full
evaluation, 406/3,000 trajectories pass released strict and 394/3,000 pass
executable strict, for 97.04% executable precision. The preceding train
window has released-strict reward 0.2725, executable-strict success 0.2634,
96.65% executable precision, 0.29% transient off-policy cancellation errors,
and 0.01% truncation.

Step 1025 falls to 18.15% over OP11–20 while retaining 8.08% over OP15–20,
but it produces the first genuine OP22 success. The single OP22 pass is held-out
index 6 and passes released strict, executable strict, and answer grading.
Manual inspection confirms the full chain: Taylor Movie Festival totals 4,
Verdi Movie Festival totals 11, and Northwood Movie Festival components 17,
11, and 22 sum to the exact answer 50. This expands observed executable-strict
prompt coverage two operations beyond the OP11–20 training range, but at only
1/200 while OP21 is zero at this checkpoint, it is a low-probability frontier
event rather than robust OP22 pass@1. OP20's two passes repeat known indices 24
and 92. Across the full evaluation, 364/3,000 trajectories pass released strict
and 357/3,000 pass executable strict, for 98.08% executable precision. The
preceding train window has released-strict reward 0.3112, executable-strict
success 0.3023, 97.11% executable precision, zero rollout errors, and 0.02%
truncation.

Step 1050 does not replicate OP22, but OP21 returns to 1.0% with
executable-strict passes on previously solved indices 25 and 90. OP11–20 is
18.90% and OP15–20 is 8.25%. OP20 reaches 1.5% on indices 43, 53, and 71;
index 53 is new, bringing cumulative executable-strict OP20 coverage to six
distinct held-out prompts. Manual inspection confirms its arithmetic from the
Cinéma de Montreval total of 7 through the Festival de Saint-Rivage total of 5
to the exact Festival de Clairmont answer 46. Across the full evaluation,
380/3,000 trajectories pass released strict and 371/3,000 pass executable
strict, for 97.63% executable precision. The preceding train window has
released-strict reward 0.2387, executable-strict success 0.2286, 95.75%
executable precision, 1.78% transient off-policy cancellation errors, and
0.01% truncation.

Step 1075 provides the strongest hard-frontier evidence so far. OP22 reaches
1.5% on three new held-out prompts, indices 68, 90, and 96; all pass released
strict, executable strict, and answer grading. Manual inspection confirms each
complete dependency chain and exact answer (51, 72, and 47). Together with
index 6 at step 1025, cumulative executable-strict OP22 coverage is now four
distinct prompts. OP21 reaches 1.0% on indices 16 and 25, with index 16 new,
bringing its cumulative coverage to five prompts. OP20 sets a new 2.5% high
and adds index 61, bringing its cumulative coverage to seven prompts. Thus the
OP21–25 aggregate reaches a new high of 0.50%, while OP11–20 and OP15–20 are
19.45% and 8.42%. This is genuine breadth expansion, but three OP22 successes
out of 200 single samples remain too sparse to establish stable pass@1.
Across the full evaluation, 394/3,000 trajectories pass released strict and
378/3,000 pass executable strict, for 95.94% executable precision. The
preceding train window has released-strict reward 0.2925, executable-strict
success 0.2791, 95.43% executable precision, 1.84% transient off-policy
cancellation errors, and 0.27% truncation.

Step 1100 provides the first direct OP22 prompt replication. OP22 index 6
passes again at 0.5%, 75 updates after its step-1025 success; the response hash
is different, and manual inspection confirms a newly sampled, complete chain
to answer 50. OP21 also scores 0.5% on new index 27, bringing cumulative
executable-strict OP21 coverage to six distinct prompts. OP20 is zero at this
checkpoint, illustrating the variance of these single-sample estimates.
OP11–20 rebounds to 20.35% and OP15–20 ties its best value at 9.08%, while the
preceding 25-step released-strict train reward reaches 0.3370. Across the full
evaluation, 409/3,000 trajectories pass released strict and 400/3,000 pass
executable strict, for 97.80% executable precision. The train window has
executable-strict success 0.3324, 98.63% executable precision, 0.67% transient
off-policy cancellation errors, and zero truncation.

Step 1125 produces a third independent executable-strict solution for OP22
index 6, after steps 1025 and 1100. All three responses have distinct hashes,
and the newest trajectory again executes cleanly to answer 50. OP21 repeats
known index 90 and OP20 repeats indices 71 and 92. This pattern identifies a
prompt-specific solvable pocket: the model has genuine OP22 breadth, but
success remains concentrated on a few instances rather than representing
uniform operation-count generalization. OP11–20 is 20.10%, OP15–20 is 8.58%,
and OP21–25 is 0.20%. Across the full evaluation, 404/3,000 trajectories pass
released strict and 395/3,000 pass executable strict, for 97.77% executable
precision. The preceding train window has released-strict reward 0.2083,
executable-strict success 0.2005, 96.25% executable precision, 2.00% transient
off-policy cancellation errors, and 0.03% truncation.

Step 1150 regresses to 18.50% over OP11–20 and 7.75% over OP15–20, with no
strict success on OP20–25. The preceding train reward is nevertheless 0.2814,
again showing that a sampled 25-step training window is not a monotonic proxy
for held-out frontier performance. The absence of OP21 and OP22 successes also
confirms that their recent crossings remain low-probability rather than stable
per-checkpoint pass@1. Across the full evaluation, 370/3,000 trajectories pass
released strict and 358/3,000 pass executable strict, for 96.76% executable
precision. The train window has executable-strict success 0.2772, 98.50%
executable precision, 2.05% transient off-policy cancellation errors, and
0.05% truncation.

Step 1175 rebounds to 19.70% over OP11–20 and 9.00% over OP15–20. OP20
reaches 2.0% on known indices 52, 53, 71, and 92; OP21 repeats known index 90
at 0.5%; and OP22 returns to zero. Across the full evaluation, 395/3,000
trajectories pass released strict and 383/3,000 pass executable strict, for
96.96% executable precision. The preceding train window has released-strict
reward 0.2480, executable-strict success 0.2295, 92.50% executable precision,
zero rollout errors, and 0.02% truncation.

The lower train precision is highly correlated within sampled problem groups,
not a broad or monotonic verifier-hacking collapse. All 238 released-only
positives come from 24 unique prompts; four prompt-step groups contribute 137
of them (57.6%). Forward-reverse problems account for 209/238 disagreements
and have 71.49% executable precision among released positives, whereas
normal-forward problems remain at 98.81%. The dominant defects are false
symbolic solver equalities (`solver_equation_mismatch`, 198 rows) and false
written equality chains (`equation_mismatch`, 92 rows, overlapping). These are
the known released-verifier blind spot: the final answer and parsed graph can
match while the displayed algebra is false. Forward-reverse precision was
similarly low at step 925 (72.26%) and recovered in intervening windows, so the
step-1175 dip is explained by prompt-group composition rather than a sustained
downward trend. It still contributes an absolute 1.86 percentage points of
incorrect released reward and remains important to monitor.

Step 1200 rebounds to 21.65% over OP11–20 and sets a new OP15–20 high of
9.58%. OP20 passes known indices 61 and 92, OP21 passes known index 140, and
OP22 index 6 passes for a fourth checkpoint. Its response has a fourth distinct
hash and manually executes cleanly to answer 50, strengthening the evidence
for a prompt-specific OP22 solvable pocket. Across the full evaluation,
435/3,000 trajectories pass released strict and 425/3,000 pass executable
strict, for 97.70% executable precision. The preceding train window has
released-strict reward 0.3324, executable-strict success 0.3295, and 99.11%
executable precision. This immediate recovery from 92.50% at step 1175
directly supports the prompt-composition explanation rather than a continuing
verifier-collapse trend. The window has 2.00% transient off-policy
cancellation errors and 0.06% truncation.

Step 1225 sets a new 25-step train-reward high of 0.3914 and a new OP21–25
strict high of 0.60%. OP21 reaches 2.0% on indices 13, 22, 29, and 140; the
first three are new. OP22 reaches 1.0% on repeated index 6 and new index 20.
OP20 reaches 1.5% and adds new index 51. Manual inspection confirms all five
new hard-frontier trajectories have complete, executable dependency chains and
exact answers. Cumulative executable-strict coverage is now eight distinct
OP20 prompts, nine OP21 prompts, and five OP22 prompts. Index 6 has also been
solved at five checkpoints with five distinct response hashes. OP11–20 is
19.65% and OP15–20 remains near its new high at 9.42%. Across the full
evaluation, 399/3,000 trajectories pass released strict and 390/3,000 pass
executable strict, for 97.74% executable precision. The train window has
executable-strict success 0.3767, 96.25% executable precision, zero rollout
errors, and 0.26% truncation. This is the clearest breadth expansion so far,
although OP21 and OP22 absolute pass@1 remain only 2.0% and 1.0%.

Step 1250 regresses to 18.10% over OP11–20 and 8.25% over OP15–20 while
retaining 0.40% over OP21–25. OP21 scores 1.5% on three known prompts. OP20
adds new index 79 and OP22 adds new index 92; manual inspection confirms both
new trajectories execute coherently to exact answers 31 and 40. Cumulative
executable-strict coverage therefore rises to nine distinct OP20 prompts, nine
OP21 prompts, and six OP22 prompts. Across the full evaluation, 366/3,000
trajectories pass released strict and 348/3,000 pass executable strict, for
95.08% executable precision. The preceding train window has released-strict
reward 0.2541, executable-strict success 0.2508, 98.71% executable precision,
0.75% transient off-policy cancellation errors, and 0.14% truncation. The
continued prompt-coverage growth despite aggregate variance is stronger
evidence of breadth than any single checkpoint's pass@1.

Step 1275 extends the genuine observed frontier to OP23, three operations
beyond the OP11–20 training range. OP23 index 165 passes released strict,
executable strict, and answer grading; manual inspection confirms its complete
chain through Jefferson Circus and Bundle Ranch to the exact Mayer Aquarium
answer 26. OP21 reaches 3.5% and adds indices 147 and 163, OP22 reaches 1.5%
and adds index 9, and OP20 reaches 3.0% and adds index 7. All five new
trajectories execute coherently. Cumulative executable-strict coverage is now
10 distinct OP20 prompts, 11 OP21 prompts, seven OP22 prompts, and one OP23
prompt. The OP21–25 aggregate therefore reaches a new high of 1.10%, even as
OP11–20 falls to 17.90% and OP15–20 is 8.67%; this contrast further exposes
the variance and prompt heterogeneity in single-sample checkpoint estimates.
Across the full evaluation, 369/3,000 trajectories pass released strict and
355/3,000 pass executable strict, for 96.21% executable precision. The
preceding train window has released-strict reward 0.3123, executable-strict
success 0.3059, 97.97% executable precision, 1.62% transient off-policy
cancellation errors, and 0.02% truncation.
