# RL configs

`op11_20_strict_grpo_r128.toml` starts from the released composition-pretrained
base and uses 128 on-policy rollouts per GSM-Infinite problem. Its only
optimization reward is the released strict dependency-graph check. Answer
correctness and the executable strict grader are logged with zero reward
weight.

Generate the fresh, balanced 2K OP11–20 prompt pool first:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch user/tianhaowu/rsci/scripts/prepare_rl_op11_20.sbatch
```

The wrapper writes `audit.json` only after checking exact per-operation counts,
unique prompt and sample IDs, all canonical completions under the strict
verifier, and zero prompt overlap with the released OP11–20 validation shards.

Validate and materialize the five-node SLURM launch without submitting it:

```bash
bash user/tianhaowu/rsci/scripts/run_rl_op11_20.sh \
  user/tianhaowu/rsci/configs/rl/op11_20_strict_grpo_r128.toml \
  --dry-run
```

Remove `--dry-run` to submit. The allocation uses one eight-GPU training node
and four one-node inference replicas. The 8,192-rollout in-flight cap is 64
problem groups, matching the measured optimum of 16 concurrent 128-rollout
groups per inference node.

The config sets `slurm.sync_environment=false` because the shared project
environment is synchronized and locked before submission, while H100 compute
nodes cannot fetch GitHub-hosted wheel metadata. The job still activates the
same shared `.venv`; rerun `uv sync --all-extras --locked` on the login side
before launching after any dependency change.

The submission environment defines a sandbox-only HTTP proxy that compute nodes
cannot reach. The SLURM pre-run command unsets those proxy variables, matching
the existing RSCI SFT/evaluation launchers, and adds every allocated hostname
plus localhost to `NO_PROXY`/`no_proxy`. Router health checks remain node-local,
while W&B uses the compute nodes' direct egress.

For a deferred allocation, submit the lightweight monitor after the RL job has
begun. It appends scheduler health, strict OP11–25 pass@1, trainer stability,
and throughput to the run's `STATUS.md` every hour:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --dependency=after:<rl-job-id> \
  user/tianhaowu/rsci/scripts/monitor_rl_run.sbatch \
  <rl-job-id> <rl-output-dir>
```

The training pool is prompt-disjoint from the full OP11–25 validation suite.
OP11–20 use the released shards. OP21–25 use the fixed frontier-extension
shards generated with seed `20260802`, `generator_op_max=30`, equal context and
direction mixtures, and 200 problems per operation. During RL, each operation
is evaluated separately with one rollout per held-out problem every 25 updates.
Use the existing RSCI evaluation pipeline for the final 128-rollout pass@k
comparison.

To continue the production run to 10,000 steps after its terminal step-500
evaluation stalled, compose the base config with the resume overlay:

```bash
bash user/tianhaowu/rsci/scripts/run_rl_op11_20.sh \
  user/tianhaowu/rsci/configs/rl/op11_20_strict_grpo_r128.toml \
  @ user/tianhaowu/rsci/configs/rl/op11_20_strict_grpo_r128_resume_10k.toml
```

The trainer wrote step 500, but the stalled orchestrator did not write matching
step-500 progress. The overlay therefore resumes the newest consistent trainer,
orchestrator, and inference-weight checkpoint at step 475 and redoes updates
475–499 before continuing. Monitor the resumed job with:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --dependency=after:<rl-job-id> \
  user/tianhaowu/rsci/scripts/monitor_rl_run.sbatch \
  <rl-job-id> <rl-output-dir> 10000
```

## Behavior-conditioned verifier-defect sweep

The 1%, 5%, and 10% treatments use the completed clean strict-reward run as
their 0% control. Behavior \(A\) is defined deterministically as a trajectory
whose final answer is correct but whose released dependency graph is not
strictly correct:

\[
A=\mathtt{answer\_correct}\land\neg\mathtt{strict\_dependency\_graph}.
\]

For a fresh rollout identifier, the environment draws an agent-independent
Bernoulli variable \(B\sim\operatorname{Bernoulli}(p_A)\) and trains on

\[
R_{\mathrm{proxy}}=R_{\mathrm{strict}}+A B.
\]

Thus 1%, 5%, and 10% are conditional false-positive probabilities among
answer-correct, strict-CoT-wrong trajectories. They are not percentages of all
rollouts. Correct strict trajectories always receive reward 1, and incorrect
answers never receive defect reward in this experiment.

Each treatment is a standalone copy of the proven control config. It starts at
step zero from the same released pretrained model and retains the control's
training data, prompt-source seed, inference seed, 128 rollouts per prompt,
batch size 512, sampling parameters, optimizer, KL coefficient, 10,000-step
budget, checkpoint cadence, deployment, and clean OP11–25 validation suite.
Only the proxy-reward probability and run identity change.

Training logs separate the optimized proxy from the target metric:

- `reward/op11-20-strict/mean`: corrupted proxy reward used by GRPO;
- `metrics/op11-20-strict/strict_dependency_graph_reward`: uncorrupted released-strict CoT correctness;
- `metrics/op11-20-strict/executable_strict_metric`: uncorrupted executable CoT correctness;
- `metrics/op11-20-strict/answer_correct_metric`: final-answer correctness;
- `defect_candidate_metric`, `defect_triggered_metric`, and `defect_draw_metric`: intervention audit fields.

The defect arguments occur only on the training environment. Every held-out
environment therefore continues to use clean strict reward, making periodic
OP11–25 validation directly comparable with the 0% control.

Materialize and inspect a treatment before submission:

```bash
bash user/tianhaowu/rsci/scripts/run_rl_op11_20.sh \
  user/tianhaowu/rsci/configs/rl/op11_20_strict_grpo_r128_defect_p01.toml \
  --dry-run
```

Remove `--dry-run` to submit. Replace `p01` with `p05` or `p10` for the later
treatments. Launch the 1% arm first and verify the proxy/strict separation and
realized intervention rate before escalating to 5% and 10%.

The primary endpoint is mean clean strict pass@1 on hard OOD OP21–25 over the
20 evaluations from steps 9,500 through 9,975. Report step 9,975 and the
corresponding OP11–20 and OP15–20 aggregates as secondary endpoints. Also run
the same clean 128-rollout evaluator on every fixed step-10,000 checkpoint; do
not select a different best checkpoint independently for each treatment.

## OP10–40 training pool and OP41–45 evaluation set

The harder verifier-defect sweep uses a fresh fixed pool with 1,000 unique
training prompts for each operation from OP10 through OP40: 31,000 training
prompts in total. Its clean held-out set contains 200 prompts for each of
OP41–45, or 1,000 evaluation prompts. The generation protocol is deterministic:

- OP10–20 training uses seed `20260803` and the released generator schedule;
- OP21–30 training uses seed `20260803` and `generator_op_max=30`;
- OP31–40 training uses seed `20260803` and `generator_op_max=40`;
- OP41–45 evaluation uses seed `20260802` and `generator_op_max=50`;
- every shard uses equal zoo/teacher/movie context weights and equal
  forward/reverse direction weights;
- generation allows up to 50,000 deterministic attempts per requested sample.

Submit the 36-way CPU array and its `afterok` finalizer with:

```bash
bash user/tianhaowu/rsci/scripts/submit_rl_op10_40_data.sh
```

The command is idempotent: it exits if the finalized dataset is valid, reports
an active preparation job instead of duplicating it, and safely reuses complete
operation shards on a retry. Outputs are written to
`/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-31k`.
`dataset_manifest.json` is the final readiness marker; `audit.json` records
exact per-operation counts, globally unique prompt and sample IDs, canonical
strict-grader success, and zero train/evaluation overlap.

The no-repeat capacity gate is 20,064 distinct task pulls:

\[
5000\left(\frac{512}{128}\right)+\frac{8192}{128}
= 5000\cdot4+64
= 20064.
\]

The 31,000-prompt pool therefore leaves 10,936 prompts of headroom, or 54.5%
relative to the nominal capacity requirement. This bound covers 5,000 updates
only when each update consumes exactly four task groups. Enforced
zero-advantage filtering consumes prompts from homogeneous-reward groups
without advancing the optimizer step. Those rejected groups count against the
no-repeat budget. With the orchestrator's guard of at most nine consecutive
empty four-group batches before a successful batch, a worst-case 5,000-step
run can consume up to

\[
5000\left(10\frac{512}{128}\right)+\frac{8192}{128}=200064
\]

distinct prompts. Thus 31,000 is sufficient for the nominal schedule but is
not a hard no-repeat guarantee for a sparse-reward arm. Check the observed
finished-group count before claiming no reuse.

The matched hard-task sweep has five standalone configs:

- `op10_40_strict_grpo_r128_defect_p00.toml`;
- `op10_40_strict_grpo_r128_defect_p01.toml`;
- `op10_40_strict_grpo_r128_defect_p05.toml`;
- `op10_40_strict_grpo_r128_defect_p10.toml`;
- `op10_40_strict_grpo_r128_defect_p20.toml`.

Every arm starts from the same base checkpoint and differs only in run identity
and the training false-positive probability. The p00 arm is a fresh strict
control. Training optimizes `reward/op10-40-strict/mean`; the uncorrupted target
is logged as
`metrics/op10-40-strict/strict_dependency_graph_reward`. Held-out OP41–45
environments omit defect arguments, so their `eval/heldout-opNN-strict/avg@1`
metrics are clean strict pass@1.

For the full generalization curve, evaluate frozen checkpoints on strict
pass@1 for every operation from OP11 through OP45. The 7,000-prompt suite uses
the released OP11–20 shards, fixed generated OP21–30 and OP31–40 shards, and
the experiment's OP41–45 shards. All prompts are globally unique, canonical
solutions pass the strict grader, and none overlap the 31,000 training prompts.
Run it outside the asynchronous trainer so every arm is measured at a stable
policy version without changing training throughput:

```bash
bash user/tianhaowu/rsci/scripts/submit_rl_checkpoint_eval.sh \
  /checkpoint/ram-h100-2/tianhaowu/rsci/rl/base-op10-40-strict-r128-defect-answer-p05 \
  100
```

The one-GPU job writes per-operation and aggregate strict and answer-only
pass@1 under `RUN_DIR/evals/op11-45/step_STEP/metrics.json`. The checkpoint must
contain its `STABLE` marker. Use the same fixed checkpoint steps for every arm.
Evaluation servers use a job-local vLLM compiler cache so concurrent launches
do not share mutable cache entries.

These configs use the checkpoint's native 2,048-token trainer and inference
context, matching the earlier sweep. A runtime smoke test showed that merely
setting `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1` is unsafe for this checkpoint: the
first sequence to cross token 2,048 triggered a CUDA device-side assertion.
Canonical prompt-plus-solution lengths exceed 2,048 for 11, 12, 14, 21, and 27
of the 200 rows at OP41 through OP45 respectively. Report the logged truncation
rate with strict pass@1; a separate, explicitly trained/tested RoPE-extension
experiment is required to remove this context ceiling.

Dry-run an arm before submission:

```bash
bash user/tianhaowu/rsci/scripts/run_rl_op10_40.sh \
  user/tianhaowu/rsci/configs/rl/op10_40_strict_grpo_r128_defect_p20.toml \
  --dry-run
```

When data preparation is still active, submit the generated `rl.sbatch` with
an `afterok` dependency on the finalizer. This guarantees that the environment
cannot start from a partial or unaudited dataset.
