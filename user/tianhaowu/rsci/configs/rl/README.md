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
- `defect_candidate_metric`: answer-correct/strict-wrong behavior, independent of which trajectories are eligible;
- `defect_eligible_metric`: trajectories eligible under the configured false-positive scope;
- `defect_triggered_metric` and `false_negative_triggered_metric`: realized reward flips;
- `defect_draw_metric` and `defect_rate_metric`: reproducible draw and effective conditional rate.

The environment also supports causal controls without changing the production
sweep defaults:

- `false_positive_scope = "uniform_strict_wrong"` makes every strict-negative
  behavior equally eligible, so expected proxy reward is an affine transform of
  strict reward;
- `defect_draw_scope = "sample"` makes the draw persistent for a prompt instead
  of fresh per trajectory;
- `defect_draw_scope = "sample_slot"` hashes `(sample_id, rollout_slot)` for a
  complete scored group. This is the confirmatory paired-run scope: changing
  trajectory UUIDs does not change the draws, and every 1% trigger is also a 5%
  trigger whenever the same prompt-slot remains eligible;
- `false_negative_rate` independently removes strict-positive rewards;
- `false_positive_rates_by_op = { "20" = 0.01, ... }` overrides the default
  false-positive rate on selected operations.

Set `defect_assignment = "behavior_group"` or `"shuffled_group"` for the
matched group control. Let `K` be the eligible answer-correct/strict-wrong
count and `H` the number whose configured defect draw fires. The behavior mode
rewards those `H` trajectories; the shuffled mode reassigns exactly `H` rewards
to independently ranked strict-negative trajectories. Their per-group reward
histograms and zero-advantage status are
therefore identical. Use a `behavior_group` arm with rate zero as the clean
control so all arms share group scoring and partial-group failure semantics.

Group modes additionally log both counterfactual proxy vectors,
`behavior_triggered_metric`, `shuffled_triggered_metric`,
`shuffle_draw_metric`, `defect_rollout_slot_metric`,
`matched_extra_positive_count_metric`, and `valid_rollout_metric`. The shuffled
control removes the trajectory-level link between the candidate behavior and
reward, but realized `H` is still drawn from that group's eligible count `K`;
it is not fully behavior-independent noise.

Use `sample_slot` for paired behavior/shuffled and cross-dose runs. The legacy
`trajectory` scope hashes a newly generated UUID, so equal `defect_seed` values
alone do not create common random numbers across independent jobs. Group order
is stable because the legacy bridge constructs inputs in slot order and
`asyncio.gather` returns results in input order. The framework stamps reserved
slot metadata before computing group metrics, and the environment validates and
logs it.

This couples verifier randomness only; independently trained policies can still
produce different eligible counts `K` and therefore different realized counts
`H`. It also makes the defect persistent for a repeated
`(sample_id, rollout_slot)`. The 500-step
31K-prompt pilot consumes no prompt twice, so persistence does not alter that
pilot's estimand. Add a deterministic exposure index before using this scope in
a run that reshuffles and revisits prompts.

The five confirmatory pilot overlays retain stable inference weights at every
25-step evaluation boundary (`ckpt.keep_interval = 25`). The asynchronous live
OP11--45 eval is a health diagnostic only: the current dispatcher can resume
training after the eval queue is dispatched, so one epoch may mix adjacent
policy versions. Primary exposure AUC and discovery endpoints must come from
the retained checkpoints evaluated with `prepare_rl_checkpoint_eval.py`; reject
mixed-policy live points rather than assigning them a causal exposure.

Any operation-specific keys must fall within the environment's configured
`min_op`--`max_op` range. Keep these arguments off held-out environments.

For confirmatory group-level studies, set
`orchestrator.save_train_group_stats = true`. This writes compact pre-filter
metric arrays for every finalized group and a separate manifest of the exact
group slices in every assembled batch attempt. These files include groups that
post-batch zero-advantage filtering removes; ordinary step JSONL omits entirely
empty attempts and excludes the internal `group_id`. Group records include both
verifier-reported rollout slots and expected positional slots, so synthetic
request failures that never reached group scoring remain distinguishable.

Replay deterministic behavior-conditioned and shuffled counterfactuals on this
complete audit trail with:

```bash
uv run --no-sync user/tianhaowu/rsci/analyze_verifier_group_counterfactuals.py \
  RUN_OUTPUT_DIR --p 0 0.01 0.05 0.10 0.20 --output counterfactuals.json
```

The analyzer accepts the experiment root, `run_default`, or its `rollouts`
directory. It validates group/trace uniqueness and exact batch-slice offsets
before reporting mixed-group, trainable-row, and empty-attempt rates.

For legacy runs that saved only shipped `train_rollouts.jsonl` cohorts, audit
the difficulty distribution of gradient-bearing groups with:

```bash
uv run --no-sync user/tianhaowu/rsci/analyze_verifier_curriculum_rotation.py \
  --train-dataset /path/to/train.jsonl \
  --run p00=/path/to/p00 --run p01=/path/to/p01 --run p05=/path/to/p05 \
  --cutoff p00=STEP --cutoff p01=STEP --cutoff p05=STEP \
  --window-size 300 --output curriculum-rotation.json
```

This parser snapshots a contiguous step prefix, binds every input by SHA-256,
validates the exact reward algebra, and admits only exact 128-row task groups
from the same or adjacent saved steps. Its estimand is explicitly conditional
on shipped nonempty cohorts: it cannot recover empty attempts or population
defect prevalence. Use the complete group/attempt audit below for confirmatory
causal analysis.

For the pinned legacy sweep, reproduce the matched raw-exposure versus
optimizer-step comparison and the saved-cohort selection diagnostic with:

```bash
uv run --no-sync user/tianhaowu/rsci/analyze_verifier_threshold_audit.py \
  --output /path/to/verifier-defect-threshold-audit.json
```

The default inputs are the immutable descriptive and curriculum summaries
recorded by the study. Override both paths and expected SHA-256 values together
for another frozen analysis. The audit verifies every rollout and log prefix,
uses the exact mixed-gate probability
`1 - (1 - p)^K - 1[K = V] p^K`, and fails if its implementation changes while
running. Its activation rates remain conditional on shipped legacy cohorts;
they are not population nucleation estimates.

Analyze the randomized innovation on the raw batch-attempt clock with:

```bash
uv run --no-sync user/tianhaowu/rsci/analyze_verifier_causal_attempts.py \
  RUN_OUTPUT_DIR \
  --lags 0 1 2 4 8 16 32 \
  --placebo-leads 1 2 4 8 \
  --output causal-attempts.json
```

Here `K` is the eligible answer-correct/strict-wrong count, `H` is the
realized behavior-coin count, `Q = H - p K`, and
`VQ = p (1 - p) K`. In a shuffled arm, `H` still determines the matched reward
budget even though the independently ranked strict-negative recipients differ.
The analyzer includes every assembled attempt, including empty attempts, and
treats shipping and `n_trainable` as outcomes. It audits the resolved
pre-batch filters, rejects repeated `(sample_id, rollout_slot)` coin keys, and
binds the three inputs and analyzer implementation by byte size and SHA-256.
Its `R_L = p * sum_l beta_l^(K)` self-excitation summary is an exploratory point
estimate over the requested positive lags, not a criticality or phase-transition
claim. Group gate `M` means that the proxy reward vector is mixed; another
enforced post-batch filter can still prevent shipping.

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

## OP10–40 training pool and OP11–45 evaluation suite

The harder verifier-defect sweep uses a fresh fixed pool with 1,000 unique
training prompts for each operation from OP10 through OP40: 31,000 training
prompts in total. The same preparation job creates 200 clean held-out prompts
for each of OP41–45. In-training evaluation combines those 1,000 prompts with
the immutable 200-prompt shards for every operation from OP11 through OP40,
giving 7,000 strict-evaluation prompts over OP11–45. The generation protocol
is deterministic:

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
no-repeat budget. These configs set
`max_consecutive_zero_trainable_batches = 100`, allowing at most 99 consecutive
empty four-group batches before a successful batch; the 100th consecutive empty
batch still aborts. This safety threshold changes neither rewards nor gradients.
A worst-case non-aborting 5,000-step run can consume up to

\[
5000\left(100\frac{512}{128}\right)+\frac{8192}{128}=2000064
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
control. The restarted arms use fresh output directories, W&B names, and SLURM
job names ending in `-eval11-45-v2`, so earlier artifacts are not resumed or
overwritten. Training optimizes `reward/op10-40-strict/mean`; the uncorrupted
target is logged as
`metrics/op10-40-strict/strict_dependency_graph_reward`. Every OP11–45
evaluation environment omits defect arguments, so
`eval/heldout-opNN-strict/avg@1` is clean strict pass@1 for that operation.
Each environment evaluates its fixed 200 prompts with one rollout per prompt at
step 0 and every 25 optimizer steps.

The 500-step matched pilot and uniform-noise comparator use the p00 config as a
base plus one of these overlays:

- `op10_40_group_scored_clean_p00_pilot500.toml`;
- `op10_40_behavior_group_p01_pilot500.toml`;
- `op10_40_shuffled_group_p01_pilot500.toml`;
- `op10_40_behavior_group_p05_pilot500.toml`;
- `op10_40_shuffled_group_p05_pilot500.toml`;
- `op10_40_uniform_fpr_match_p05_pilot.toml`.

### Commit-pinned runtime source

The pilot overlays run from an immutable source snapshot under each run
directory, rather than from the mutable checkout used to submit the job.
After committing the intended parent and submodule revisions, create the
snapshot before materializing `rl.sbatch`:

```bash
RUN_DIR=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/RUN_NAME
SOURCE_COMMIT=$(git rev-parse HEAD)
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create \
  "$RUN_DIR" --commit "$SOURCE_COMMIT"
```

Creation archives the parent commit and every pinned submodule commit, makes
the source tree read-only, links its `.venv` to the shared environment, and
writes `source_provenance.json` plus `source_environment.freeze.txt`. The
manifest records the parent and submodule SHAs, source-tree digest, `uv.lock`
hash, and normalized `uv pip freeze` hash. It also verifies that `prime_rl`,
`prime_rl.configs`, `rsci_gsm_infinite`, and `verifiers` import from the
snapshot. Dirty working-tree content is deliberately absent.

The content digest covers the exact runtime closure (`src`, prime-rl configs,
RSCI, and the pinned renderer/verifier/config dependencies) rather than
unimported documentation and tests. The full parent and submodule commits remain
recorded. Runtime activation pins `UV_PROJECT_ENVIRONMENT` to the recorded
shared environment so `uv` cannot create a path-keyed environment for each
snapshot.

The overlays set `slurm.project_dir` to their own `RUN_DIR/source_snapshot` and
source `activate_source_snapshot.sh` before starting any component. Materialize
the launch from the pinned base and overlay configs inside that snapshot, then
seal it:

```bash
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" materialize-launch \
  "$RUN_DIR" \
  user/tianhaowu/rsci/configs/rl/op10_40_strict_grpo_r128_defect_p00.toml \
  user/tianhaowu/rsci/configs/rl/op10_40_shuffled_group_p05_pilot500.toml
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" seal-launch "$RUN_DIR"
```

`materialize-launch` first verifies the unsealed snapshot, then invokes the
snapshot's pinned `rl` entrypoint with a snapshot-only Python path and
`--dry-run`. Repository-relative config arguments resolve only inside the
snapshot. It records the exact command and generated hashes; `seal-launch`
refuses a missing materialization or any byte changed afterward. The normal
activation guard is intentionally deferred because it requires a completed
seal. No generated workload may start until `seal-launch` succeeds; runtime
activation then occurs before the script's first project import.

The seal adds SHA-256 hashes for `rl.sbatch` and every materialized
`RUN_DIR/configs/*.toml` to `source_provenance.json`. It also hashes the actual
bytes of every dataset referenced by the resolved train and eval environments,
the full base-model directory while following Hugging Face cache symlinks, the
tokenizer directory, and the configured chat template. Each matching data hash
is also checked against the authoritative `dataset_manifest.json` when that
manifest is present. The generated training script sources the activation guard
before its first `uv run`, and the guard rechecks the source, shared environment,
resolved configs, script hashes, and sealed external inputs. Both training and
frozen-checkpoint evaluation refuse
an unsealed, missing, modified, wrong-commit, input-mismatched, or
environment-mismatched snapshot. A source, input, or shared-environment change
requires a fresh run directory; never replace a snapshot under an existing run
identity.

Pass the base and overlay as separate repository-relative arguments to
`materialize-launch`; each becomes a pinned `@` config in the recorded command:

```bash
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" materialize-launch \
  "$RUN_DIR" \
  user/tianhaowu/rsci/configs/rl/op10_40_strict_grpo_r128_defect_p00.toml \
  user/tianhaowu/rsci/configs/rl/op10_40_shuffled_group_p05_pilot500.toml
```

The in-training generalization curve uses the released OP11–20 shards, fixed
generated OP21–30 and OP31–40 shards, and the experiment's OP41–45 shards. All
prompts are globally unique, canonical solutions pass the strict grader, and
none overlap the 31,000 training prompts. For a frozen-checkpoint audit, run the
same suite outside the asynchronous trainer so every arm is measured at an
explicit stable policy version. The batch submitter schedules the fixed grid
`0, 25, ..., 500`, with one checkpoint and one H100 per array task:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  bash user/tianhaowu/rsci/scripts/submit_rl_checkpoint_eval_array.sh \
  --dependency afterok:TRAINING_JOB_ID \
  --max-parallel 8 \
  RUN_DIR
```

Omit `--dependency` after training has terminated. Step 0 resolves the immutable
base model from the run's materialized `configs/trainer.toml`; every positive
step requires `weights/step_STEP/STABLE`. The submitter is idempotent: it returns
the live array job for a repeated submission and excludes only steps whose
complete artifact set passes the same strict validator used by the confirmatory
analyzer. An interrupted task preserves `generations.jsonl`, so a later
submission resumes that step. Manifests and array logs live under
`RUN_DIR/evals/op11-45/array/`.

Each task writes per-operation and aggregate strict and answer-only pass@1 to
`RUN_DIR/evals/op11-45/step_STEP/metrics.json`. Concurrent tasks use distinct
local ports and job-local vLLM compiler caches. A stable seed derived from each
prompt identity gives every arm common evaluation randomness; identical step-0
models must therefore produce identical generations and scores. The single-step
helper remains available for a targeted retry:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  bash user/tianhaowu/rsci/scripts/submit_rl_checkpoint_eval.sh RUN_DIR 100
```

Capture the array job ID printed by the batch submitter as `ARRAY_JOB_ID`. Give
the CPU monitor an `afterany` dependency on the training job, not the evaluation
array; on successful training it starts alongside the `afterok` evaluation
array, while a failed training dependency is still reported:

```bash
BATCH_DIR="$RUN_DIR/evals/op11-45/array"
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --parsable \
  --dependency="afterany:$TRAINING_JOB_ID" \
  --output="$BATCH_DIR/monitor_%j.log" \
  --error="$BATCH_DIR/monitor_%j.log" \
  "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/scripts/monitor_rl_checkpoint_eval.sbatch" \
  "$RUN_DIR" "$ARRAY_JOB_ID"
```

The `cpu_lowest` monitor checks the array every minute. It records per-task live
or accounting states and validates each marker against its strict results,
resolved configs, exact model, dataset hashes, sampling seed, and implementation
provenance. It atomically updates `RUN_DIR/evals/op11-45/array/status.json` with
the valid count, rolling throughput, and ETA. It exits successfully at 21/21. If
every producer has terminated first, it writes `stopped-incomplete` and exits
nonzero. Purged `squeue` IDs are recovered through `sacct`; a newly submitted ID
gets a bounded five-minute scheduler-discovery grace period. Each submission
also writes
`array/jobs/ARRAY_JOB_ID.json`, preserving its exact task-to-step mapping even
for partial retries. Invalid markers remain incomplete; a retry worker moves
them to a content-addressed
`metrics.invalid.ARRAY_JOB_ID.taskN.SHA256.json` before resuming. If training
fails, pending `DependencyNeverSatisfied` tasks produce a
`stopped-incomplete` status with that explicit reason.

Every frozen evaluation writes `generation_manifest.json` before requesting
tokens. It binds the resolved model inventory, dataset paths and hashes, ordered
prompt identities, generation sampling fields, per-rank request-seed contract,
normalized semantic inference settings, and the exact evaluator/scorer source
contents. Transport ports, output paths, and logging do not change the contract;
dtype, context length, engine options, model contents, or scorer contents do.
Resume is allowed only when that contract and every existing
`(op, __idx, id, sample_rank)` agree. A stale bundle is moved recoverably under
`quarantine/` before generation restarts. Once complete,
`generation_completion.json` and `metrics.json` record both the raw JSONL hash
and an order-independent canonical generation hash; the latter is the CRN
identity used to compare shared step-0 generations across arms. Validation also
re-scores every bound generation with the pinned strict scorer and requires the
exact `strict_results.jsonl` contents and scoring provenance to match.

After all five matched arms are valid, produce the preregistered exposure audit
at the fixed `E* = 256,000` generated rollouts:

```bash
uv run --no-sync user/tianhaowu/rsci/analyze_verifier_exposure.py \
  --analysis-tier confirmatory-audit \
  --e-star 256000 \
  --run C0=/path/to/clean-run \
  --run B1=/path/to/behavior-p01-run \
  --run S1=/path/to/shuffled-p01-run \
  --run B5=/path/to/behavior-p05-run \
  --run S5=/path/to/shuffled-p05-run \
  --output-json /path/to/verifier-defect-confirmatory.json \
  --output-svg /path/to/verifier-defect-confirmatory.svg
```

Confirmatory mode refuses mixed-policy live evaluations, missing scheduled
checkpoints inside the `E*` bracket, changed datasets or evaluator hashes,
nonidentical shared-base step-0 scores, and unbracketed exposure. Use
`--analysis-tier descriptive-v2` explicitly for the legacy log-proxy curves;
there is no automatic fallback between tiers.

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
