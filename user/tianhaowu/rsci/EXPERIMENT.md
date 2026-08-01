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
