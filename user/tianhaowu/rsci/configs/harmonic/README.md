# Harmonic pass@k SFT runbook

This runbook defines the harmonic pass@k weighting used by
`harmonic_build_dataset.py`, derives the formula, and records the operational
steps for building, auditing, training, selecting, evaluating, and plotting the
RSCI OP11–14 experiment.

The short version is: estimate each problem's single-sample success probability
from 128 frozen base-model rollouts, retain only answer-correct trajectories,
and weight every retained trajectory by the marginal value of increasing that
probability under a harmonic mixture of inference budgets.

## Quick reference

For problem \(x\):

- \(n=128\): number of frozen collection rollouts.
- \(c_x\): number of answer-correct rollouts.
- \(\hat p_x=c_x/n\): empirical single-sample success rate.
- \(K\): largest budget in the harmonic training objective; this experiment
  uses \(K\in\{4,8,16,32,64\}\).
- \(H_K=\sum_{b=1}^K 1/b\): the \(K\)-th harmonic number.

Every answer-correct trajectory for problem \(x\) receives

\[
w_K(\hat p_x)
=\frac{1}{H_K}\sum_{j=0}^{K-1}(1-\hat p_x)^j.
\]

For \(\hat p_x>0\), the equivalent closed form is

\[
w_K(\hat p_x)
=\frac{1-(1-\hat p_x)^K}{\hat p_x H_K}.
\]

Incorrect trajectories are excluded. A problem with \(c_x=0\) therefore
contributes no SFT rows.

## Why this is called harmonic pass SFT

Let \(p\) be the probability that one independent model sample solves a
problem. The probability that at least one of \(b\) samples succeeds is

\[
P_b(p)=\operatorname{pass@b}(p)=1-(1-p)^b.
\]

Define a random inference budget (B\in\{1,\ldots,K\}) with

\[
\Pr(B=b)=\frac{1}{bH_K}.
\]

These probabilities sum to one because
\(\sum_{b=1}^K 1/(bH_K)=1\). The normalized harmonic-budget objective is

\[
J_K(p)
=\mathbb E_B[P_B(p)]
=\frac{1}{H_K}\sum_{b=1}^K\frac{1}{b}
  \left[1-(1-p)^b\right].
\]

Differentiate with respect to the single-sample success probability:

\[
\begin{aligned}
\frac{dJ_K}{dp}
&=\frac{1}{H_K}\sum_{b=1}^K\frac{1}{b}
  b(1-p)^{b-1} \\
&=\frac{1}{H_K}\sum_{b=1}^K(1-p)^{b-1} \\
&=\frac{1}{H_K}\sum_{j=0}^{K-1}(1-p)^j \\
&=w_K(p).
\end{aligned}
\]

Thus the implemented weight is the marginal gain in the harmonic-budget
objective from improving \(p\). “Harmonic” refers to the inverse-budget
distribution \(1/(bH_K)\); \(J_K\) is an inverse-budget-weighted arithmetic
mean, not a harmonic mean of pass@b values.

It is also not the derivative of pass@K alone. That derivative would be

\[
\frac{dP_K}{dp}=K(1-p)^{K-1},
\]

which is a different objective and a different weighting rule.

## Why successful trajectories get this weight

Let \(\pi_\theta(y\mid x)\) be the model policy and let
\(r(x,y)\in\{0,1\}\) denote answer correctness. The model's single-sample
success probability is

\[
p_\theta(x)=\mathbb E_{y\sim\pi_\theta(\cdot\mid x)}[r(x,y)].
\]

The score-function identity gives

\[
\nabla_\theta p_\theta(x)
=\mathbb E_{y\sim\pi_\theta}
 \left[r(x,y)\nabla_\theta\log\pi_\theta(y\mid x)\right].
\]

Applying the chain rule,

\[
\nabla_\theta J_K(p_\theta(x))
=w_K(p_\theta(x))
 \mathbb E_{y\sim\pi_\theta}
 \left[r(x,y)\nabla_\theta\log\pi_\theta(y\mid x)\right].
\]

With \(n\) sampled trajectories, the plug-in Monte Carlo direction is

\[
\widehat{\nabla_\theta J_K}
=\frac{w_K(\hat p_x)}{n}
 \sum_{s=1}^{n}r_s\nabla_\theta\log\pi_\theta(y_s\mid x).
\]

Because \(n=128\) is the same for every problem, \(1/n\) is a global scale.
The dataset therefore keeps each successful trajectory once and assigns it
\(w_K(\hat p_x)\). Do not divide the row weight by \(c_x\): the sum over the
successful rows is part of the estimator.

This derivation motivates the offline SFT surrogate at the frozen collection
policy. The builder estimates \(\hat p_x\) once from the base policy and never
updates it during SFT. As the trained policy moves away from the collection
policy, the procedure is weighted behavior cloning rather than an unbiased
on-policy gradient estimator.

## Properties and sanity checks

The finite geometric sum is used in code and remains defined at \(p=0\). Its
main properties are:

1. **Unweighted special case:** \(K=1\Rightarrow w_1(p)=1\).
2. **Hardest-problem limit:** \(\lim_{p\to0^+}w_K(p)=K/H_K\).
3. **Easiest-problem value:** \(w_K(1)=1/H_K\).
4. **Hard/easy per-success ratio:** the endpoint ratio is \(K\).
5. **Monotonicity:** for \(K>1\), \(w_K(p)\) strictly decreases with \(p\).
6. **Normalized marginal scale:**
   \(\int_0^1w_K(p)\,dp=1\).

For fixed \(p>0\) and large \(K\),

\[
w_K(p)\approx\frac{1}{p(\log K+\gamma)},
\]

where \(\gamma\) is the Euler–Mascheroni constant.

The following values use \(n=128\), exactly as in the experiment:

| successes \(c_x\) | \(\hat p_x\) | \(w_4\) | \(w_8\) | \(w_{16}\) | \(w_{32}\) | \(w_{64}\) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.0078125 | 1.897617 | 2.864255 | 4.465258 | 7.000455 | 10.648717 |
| 8 | 0.0625 | 1.747383 | 2.374109 | 3.047513 | 3.442502 | 3.318540 |
| 16 | 0.125 | 1.589062 | 1.932084 | 2.086965 | 1.943696 | 1.686052 |
| 32 | 0.25 | 1.312500 | 1.324407 | 1.171318 | 0.985488 | 0.843190 |
| 64 | 0.50 | 0.900000 | 0.732999 | 0.591579 | 0.492793 | 0.421595 |
| 128 | 1.00 | 0.480000 | 0.367937 | 0.295794 | 0.246397 | 0.210797 |

The non-monotonic values across \(K\) for a fixed intermediate \(p\) are
expected. \(K\) changes the full budget mixture; it is not a simple scalar
“more hard-example weighting” knob at every \(p\).

### Worked example: 16 successes, K=8

For \(c_x=16\), \(n=128\), and \(K=8\):

\[
\hat p_x=16/128=0.125,\qquad 1-\hat p_x=0.875,
\]

\[
H_8=1+\frac12+\cdots+\frac18=2.717857142857143,
\]

and

\[
\sum_{j=0}^{7}0.875^j=5.251128673553467.
\]

Therefore

\[
w_8(0.125)=5.251128673553467/2.717857142857143
=1.932084137444114.
\]

Each of the 16 answer-correct rows receives weight (1.932084\); the other
112 rows are absent. Ignoring response-length differences, the problem has
an aggregate positive-row mass of

\[
c_xw_8(\hat p_x)=16\times1.932084=30.913346.
\]

This is not prompt balancing. In general, for equal-length completions,

\[
c_xw_K(c_x/n)
=\frac{n}{H_K}\left[1-(1-c_x/n)^K\right].
\]

The aggregate mass still increases with solvability, but it saturates instead
of growing linearly with \(c_x\). Actual influence also depends on assistant
response lengths.

## Exact prime-rl training loss

The scalar dataset weight is copied to every token in the example. With
assistant-token mask \(m_{it}\), token negative log-likelihood
\(\ell_{it}\), scalar row weight \(w_i\), and active-token count
\(T_i=\sum_t m_{it}\), prime-rl minimizes the global weighted-token mean

\[
\mathcal L
=\frac{\sum_i w_i\sum_t m_{it}\ell_{it}}
       {\sum_i w_i\sum_t m_{it}}
=\frac{\sum_i w_i\sum_t m_{it}
  [-\log\pi_\theta(y_{it}\mid x_i,y_{i,<t})]}
       {\sum_i w_iT_i}.
\]

The denominator is all-reduced across data-parallel ranks before gradient
rescaling. Consequences:

- Only assistant tokens are active in the harmonic configs.
- Longer correct completions contribute more token terms.
- Multiplying every weight in one run by the same constant changes neither the
  normalized loss nor its gradient. \(H_K\) supplies the normalized objective
  interpretation; relative weights drive optimization.
- Training and validation must select the same treatment-specific weight
  column. Validation losses are comparable across checkpoints within one \(K\),
  but not numerically across different \(K\) objectives.
- Weighted SFT requires `loss_impl = "torch"` or `"liger"`. The fused loss
  implementations do not expose per-token losses and are rejected by config
  validation.

## Training weights versus reported pass@k

Do not substitute the evaluation estimator into the weight formula.

The builder uses the iid plug-in curve

\[
1-(1-\hat p_x)^b,
\]

and differentiates its harmonic mixture. Evaluation with \(n\) observed
samples and \(c\) successes reports the unbiased finite-sample estimator

\[
\widehat{\operatorname{pass@k}}
=1-\frac{\binom{n-c}{k}}{\binom{n}{k}}.
\]

For the worked (n=128,c=16,k=8) example, the plug-in value is (0.656391\)
while the unbiased finite-sample estimate is (0.667420\). The training weight
is the derivative of the former harmonic objective, not the latter estimator.

Also keep these three quantities separate:

- \(n=128\): collection rollouts used to estimate \(\hat p\).
- \(K\in\{4,8,16,32,64\}\): maximum harmonic training budget.
- \(k\in\{1,2,4,8,16,32,64,128\}\): evaluation budget being reported.

For example, harmonic \(K=64\) optimizes an inverse-budget-weighted mixture of
pass@1 through pass@64; it does not optimize pass@64 alone.

## Build the weighted dataset

Run from the prime-rl repository root. The historical source paths below are
the immutable inputs used by the preserved experiment. Choose a new, empty
output root: the builder refuses to overwrite an existing directory.

```bash
export HARMONIC_DATA_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/harmonic-sft/<new-experiment>/data

uv run user/tianhaowu/rsci/harmonic_build_dataset.py \
  --generations /checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/base/ood-mid-op11-14/generations.jsonl \
  --scores /checkpoint/ram-h100-2/tianhaowu/rsci/evals/figure3/base/ood-mid-op11-14/strict_results.jsonl \
  --data-dir /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/datasets--Interplay-LM-Reasoning--composition/snapshots/a09d5c14c02bfa339143fb00a93274d1a84aa31d/val \
  --output-root "$HARMONIC_DATA_ROOT" \
  --tokenizer /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base \
  --operations 11 12 13 14 \
  --examples-per-operation 200 \
  --samples-per-prompt 128 \
  --train-prompts-per-operation 160 \
  --split-seed 20260803 \
  --harmonic-k 4 8 16 32 64 \
  --seq-len 2048 \
  --world-size 8 \
  --batch-size 256 \
  --micro-batch-size 4 \
  --validation-batch-size 32 \
  --validation-micro-batch-size 4
```

The builder intentionally enforces:

- aligned generation and score identities;
- exactly sample ranks 0 through 127 for every requested prompt;
- a deterministic problem-level split, so all trajectories from one problem
  are entirely in train or validation;
- final-answer correctness as the inclusion filter;
- no duplicate operations or \(K\) values;
- no sequence exceeding `seq_len`;
- an output root that does not already exist.

`strict_correct` is retained as metadata but does not control inclusion.
Every correct row from a problem uses the same self-inclusive
\(\hat p=c/128\): there is no leave-one-out estimate, smoothing, or clipping.

## Audit the dataset before training

Inspect all three manifests:

```bash
uv run python -m json.tool "$HARMONIC_DATA_ROOT/manifest.json"
uv run python -m json.tool "$HARMONIC_DATA_ROOT/train/manifest.json"
uv run python -m json.tool "$HARMONIC_DATA_ROOT/validation/manifest.json"
```

For the preserved experiment, the required headline values are:

- 102,400 source trajectories: 4 operations × 200 problems × 128 samples;
- 47,500 answer-correct trajectories;
- 37,844 training rows and 9,656 validation rows;
- 640 split-assigned training problems (453 solved and contributing rows) and
  160 validation problems (117 solved and contributing rows);
- zero overlapping prompt keys;
- weight columns `harmonic_weight_k4`, `k8`, `k16`, `k32`, and `k64`;
- no rows longer than 2,048 tokens.

Audit the row-level formula and within-problem consistency:

```bash
uv run python - <<'PY'
import math
import os
from collections import defaultdict
from pathlib import Path

from datasets import load_dataset

root = Path(os.environ["HARMONIC_DATA_ROOT"])
split_keys = {}
for split in ("train", "validation"):
    dataset = load_dataset(
        "parquet",
        data_files=str(root / split / "train-00000-of-00001.parquet"),
        split="train",
    )
    groups = defaultdict(list)
    for row in dataset:
        groups[(int(row["op"]), int(row["prompt_index"]))].append(row)

    for rows in groups.values():
        success_count = int(rows[0]["success_count"])
        assert len(rows) == success_count
        assert all(int(row["success_count"]) == success_count for row in rows)
        assert all(float(row["pass_rate"]) == success_count / 128 for row in rows)
        for k in (4, 8, 16, 32, 64):
            p = success_count / 128
            h_k = math.fsum(1 / j for j in range(1, k + 1))
            expected = math.fsum((1 - p) ** j for j in range(k)) / h_k
            assert all(
                math.isclose(float(row[f"harmonic_weight_k{k}"]), expected)
                for row in rows
            )

    split_keys[split] = set(groups)
    print(f"audited {len(dataset)} correct rows across {len(groups)} solved {split} problems")

assert split_keys["train"].isdisjoint(split_keys["validation"])
PY
```

## Resolve and smoke-test one treatment

Configs compose left to right; CLI overrides win over both files. The base
config supplies the common model, data, optimizer, and schedule. A \(K\)
overlay selects the weight column for both training and validation.

First materialize and inspect a fresh four-step K=16 smoke config without
submitting it:

```bash
export HARMONIC_SMOKE_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/harmonic-sft/<new-experiment>/smoke-k16

uv run sft \
  @ user/tianhaowu/rsci/configs/harmonic/base_op11_14_answer.toml \
  @ user/tianhaowu/rsci/configs/harmonic/k16.toml \
  --data.name "$HARMONIC_DATA_ROOT/train" \
  --val.data.name "$HARMONIC_DATA_ROOT/validation" \
  --output-dir "$HARMONIC_SMOKE_ROOT" \
  --max-steps 4 \
  --scheduler.warmup-steps 1 \
  --val.interval 2 \
  --ckpt.interval 2 \
  --ckpt.keep-last 2 \
  --wandb.name harmonic-k16-smoke \
  --dry-run

rg -n "weight_column|loss_impl|max_steps|warmup_steps|interval" \
  "$HARMONIC_SMOKE_ROOT/configs/sft.toml"
```

Confirm that `loss_impl = "torch"`, both weight columns are
`harmonic_weight_k16`, the dataset paths point to the intended split, and the
generated SLURM script uses the intended project revision. Submit that exact
resolved smoke job:

```bash
sbatch "$HARMONIC_SMOKE_ROOT/sft.sbatch"
```

Before a full sweep, require finite training and validation loss, a stable
final checkpoint, and no missing/nonpositive/nonfinite weight error.

## Run the preserved six-treatment sweep

The production driver launches the unweighted baseline plus K=4, 8, 16, 32,
and 64; waits for stable step-248 checkpoints; selects the minimum held-out
loss within each treatment; evaluates the base and all six SFT treatments on
OP15–18; and writes `comparison.json`.

```bash
sbatch user/tianhaowu/rsci/scripts/run_harmonic_sft_ablation.sbatch
```

The driver is intentionally experiment-specific. It has hard-coded preserved
root, model, and evaluation-data paths and expects the dataset manifest to
already exist. It records implementation hashes in `state.json` and refuses to
resume if a hashed implementation changes. For a new experiment root, update
the driver/constants and config output paths deliberately; do not point the
historical driver at a partially compatible directory.

Monitor these artifacts:

```text
<experiment-root>/
├── state.json
├── STATUS.md
├── data/{manifest.json,train/,validation/}
├── runs/{baseline,k4,k8,k16,k32,k64}/
│   ├── configs/sft.toml
│   ├── logs/trainer.log
│   ├── checkpoint_selection.json
│   └── weights/step_*/STABLE
├── eval/{base,baseline,k4,k8,k16,k32,k64}/metrics.json
└── comparison.json
```

The selected validation-loss values are meaningful only within their own
treatment. Do not rank different \(K\) runs by raw weighted validation loss.
Rank treatments using the common downstream evaluation protocol.

## Evaluate and plot

The driver evaluates OP15–18 with 200 problems per operation and 128 samples
per problem, reporting answer-only and strict-graph unbiased pass@1, 2, 4, 8,
16, 32, 64, and 128.

Regenerate the preserved comparison figure with:

```bash
uv run user/tianhaowu/rsci/plot_harmonic_sft.py \
  --root /checkpoint/ram-h100-2/tianhaowu/rsci/harmonic-sft/base-op11-14-answer \
  --output user/tianhaowu/rsci/figures/harmonic_sft_op15_18.svg
```

The frozen protocol, job ledger, selected checkpoints, and measured pass@k
results live in `../../EXPERIMENT.md` under “Harmonic pass SFT from the
pretrained base.”

## Failure modes and interpretation limits

- **No successes:** \(c=0\) has the theoretical limit \(K/H_K\), but there are
  no correct trajectories to train on. Harmonic SFT cannot create signal for
  completely unsolved problems.
- **No prompt balancing:** every success is retained. Total prompt influence
  depends on \(c_x\), the common row weight, and response lengths.
- **Finite-sample noise:** \(\hat p=c/128\) is a self-inclusive plug-in estimate
  with no Bayesian smoothing or confidence correction. A one-success problem
  receives the largest observed per-row weight.
- **Frozen weights:** weights describe the base collection policy and are not
  recomputed as SFT changes the model.
- **Answer-only filtering:** final-answer correctness selects rows; strict graph
  correctness is diagnostic metadata only.
- **Length effects:** the trainer normalizes by weighted assistant-token mass,
  not by number of problems or trajectories.
- **K is an objective cutoff:** K=64 is a harmonic blend of every integer
  budget 1–64, not a pass@64-only objective.
- **Evaluation uses different statistics:** reported pass@k is the unbiased
  combinatorial estimator, not the plug-in curve used in training.
- **Existing output roots:** the dataset builder refuses overwrite, while the
  stateful sweep driver resumes only when its implementation hashes match.

## Implementation map

- Weight computation and dataset construction: `../../harmonic_build_dataset.py`
- Sweep orchestration: `../../harmonic_sft_ablation.py`
- Base SFT config: `base_op11_14_answer.toml`
- Weight-column overlays: `k4.toml`, `k8.toml`, `k16.toml`, `k32.toml`, `k64.toml`
- SFT example-weight expansion: `../../../../../src/prime_rl/trainer/sft/data.py`
- Weighted loss reduction: `../../../../../src/prime_rl/trainer/sft/loss.py`
- Distributed normalization: `../../../../../src/prime_rl/trainer/sft/train.py`
- Checkpoint selection: `../../frontier_select_checkpoint.py`
- Evaluation: `../../figure3_eval.py`
- Plotting: `../../plot_harmonic_sft.py`
- Frozen experiment results: `../../EXPERIMENT.md`
