# RSCI experiment monodoc

Last updated: 2026-08-01 UTC.

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

## Result paths

- Context smoke:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/context-pretrain-id-op2-10-smoke10-special-tokens/metrics.json`
- Figure 3 base ID:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/base/id-op2-10/metrics.json`
- Figure 3 base OOD-mid:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/base/ood-mid-op11-14/metrics.json`
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
answer pass@1 and 40.00% pass@128, so collection job `9846759` continues the
answer loop.

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
6.50% pass@128, so collection job `9844325` is running. Neither loop has
reached the requested 1% next-frontier gate.

All RSCI SFT configs now target online W&B logging under `ram/rsci`. The 46
preserved historical offline streams remain the source of truth for past
runs. A metric-only replay was validated on answer op28: remote run
`bupusy2n` is `finished` with exactly 8,975/8,975 history rows. Persistent CPU
job `9833832` completed the historical migration and remains active to watch
the two frontier jobs so currently active offline runs are uploaded after
their exit records are durable. The final set audit found 46/46 local sync
markers, 45 direct status records, and the single documented OP28 replacement;
there were zero failures, extra records, or local/remote history-row
mismatches. Each successful stream is accepted only when W&B reports
`finished`; the three local exit-code-1 smoke streams retain that provenance
while accepting any terminal remote state because W&B's offline replay reports
them as `finished`.

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

A full model-facing-text audit of the latest completed cumulative snapshots
gives the current exact totals. Answer OP11-31 has 1,050,000 rows but 896,232
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
than metadata duplication. The in-progress answer OP32 and strict OP28 shards
are excluded until they enter finalized cumulative training snapshots.

None of the 50K sampled strict OP25 completions exactly matches the generator's
literal gold completion, even though all pass the dependency-graph verifier.
An oracle upper bound is therefore materially different from strict filtering.
A 50K-row oracle shard can also have 50K unique problems by generating one gold
trace per problem; using the existing OP25 prompt pool would instead yield
17,824 gold rows, or only 1,551 if restricted to problems represented in the
accepted shard. Two useful controls are consequently (1) gold completions on
the same prompts, which isolates target quality, and (2) 50K unique gold
problems, which measures the combined quality-and-diversity upper bound.

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
