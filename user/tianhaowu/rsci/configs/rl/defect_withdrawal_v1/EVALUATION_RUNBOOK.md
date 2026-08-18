# Defect-withdrawal standalone evaluation

This evaluation is frozen before continuation outcomes are inspected. It uses
one strict OP11--45 pass@1 shard for every byte-distinct model and never uses
the optimized verifier reward.

## Fixed readouts

The eight fixed checkpoint selectors are:

- canonical p5 and p0 step-4000 sources;
- ON, OFF, and CLEAN at exact stable intermediate step 4250 and final step 4375.

The p5 source is evaluated once. ON source and OFF source reuse that selector;
FROZEN adds alias transitions at analysis clocks 4250 and 4375 rather than new
checkpoint selectors or generations. FROZEN retains
`model_step=4000`; it is never described as a step-4250 or step-4375
checkpoint. The planner may deduplicate any other exact byte-identical model,
but only after comparing the complete sorted file inventory.

Each physical task runs one inference server on one H100 and generates 7,000
responses: 200 prompts for every operation from 11 through 45. The fixed
sampling contract is temperature 0.7, one sample, 2,048 output tokens, and base
request seed 20260807, with top-p 1.0, top-k -1, stop `</answer>`, and
`skip_special_tokens=false`. Every request seed is derived from the prompt
identity, so every model receives the same prompt/seed pair.

## Freeze the pre-outcome authority

Commit and push the planner, runner, dispatcher, training-ledger auditor,
dataset/fork materializers, analyzer, and this runbook first. Create a
dedicated source-only control snapshot at the canonical evaluation root:

```bash
EVAL_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-withdrawal-v1
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create \
  "$EVAL_ROOT" --commit COMMIT
source "$EVAL_ROOT/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh" \
  "$EVAL_ROOT"
uv run --no-sync user/tianhaowu/rsci/materialize_defect_withdrawal_eval.py \
  materialize-authority --eval-root "$EVAL_ROOT"
uv run --no-sync user/tianhaowu/rsci/materialize_defect_withdrawal_eval.py \
  validate-authority --authority "$EVAL_ROOT/evaluation_authority.json"
```

Authority materialization refuses pre-existing plan, result, receipt, or
submission directories. It binds the source snapshot, evaluator/scorer bytes,
both source models, every held-out shard, prompt order, all 7,000 request
seeds, exact future run paths and checkpoint steps, and the transition
estimands.

After the continuation dataset, three independent forks, run-local source
snapshots, and sealed launch artifacts are validated, freeze the training
dispatch authority while every fork is still pristine:

```bash
uv run --no-sync user/tianhaowu/rsci/dispatch_defect_withdrawal.py \
  materialize-training-authority \
  --eval-authority "$EVAL_ROOT/evaluation_authority.json"
uv run --no-sync user/tianhaowu/rsci/dispatch_defect_withdrawal.py \
  validate-training-authority \
  --authority "$EVAL_ROOT/training_dispatch_authority.json"
uv run --no-sync user/tianhaowu/rsci/dispatch_defect_withdrawal.py \
  dispatch-training --authority "$EVAL_ROOT/training_dispatch_authority.json" \
  --arm p05_on --arm p05_off --arm p00_clean --dry-run
```

The dry run is read-only. Actual dispatch additionally requires the protected
control pane and `--confirm-study-id verifier-defect-withdrawal-v1`. It rechecks
pristine forks, rejects a live selected job name, strips every inherited
`SBATCH_*` variable, and takes a fresh all-cluster resource snapshot. Pending
FCSFT, G-STAR, known-cost, or legacy `rsci-rl-op10-40-*` jobs close the gate
just like running jobs; do not queue the withdrawal arms behind them.

## Materialize the post-training plan

Do this only after all three runs have exact stable steps 4250 and 4375 and
their protected training completion evidence is available. Each run must have
a read-only canonical `training_terminal_provenance.json` produced by the
protected training dispatcher/terminalizer. It binds the fork and source
manifests, sealed `rl.sbatch`, protected submission receipt, allocation log,
all three checkpoint inventories, exact submitted-script hash, and scheduler
`COMPLETED/0:0` record with `Restarts=0`. Terminalization also independently
replays `train_group_stats.jsonl` and `train_batch_attempts.jsonl`: optimizer
steps must be exactly 4000--4374 once each, task/sample identities may not
repeat, FIFO group consumption must agree, and OFF must have at least 250/375
informative hard clean groups at steps 4250/4375. The resulting read-only
`training_ledger_audit.json` is part of terminal provenance. Plan
materialization fails closed if any such artifact is absent or changes:

```bash
uv run --no-sync user/tianhaowu/rsci/materialize_defect_withdrawal_eval.py \
  materialize-plan --authority "$EVAL_ROOT/evaluation_authority.json"
uv run --no-sync user/tianhaowu/rsci/materialize_defect_withdrawal_eval.py \
  validate-plan --plan "$EVAL_ROOT/plans/PLAN_ID/plan.json"
```

The content-addressed plan validates every fork manifest and sealed launch,
requires exact stable checkpoints, verifies the independent step-4000 copies,
and writes read-only inference, evaluation, and one-GPU batch-script artifacts.
It never substitutes a nearby checkpoint.

The task batch scripts are plan artifacts, not authorization to submit. Do not
invoke them directly. Evaluation dispatch still requires a protected
content-addressed submission intent/receipt workflow through the control tmux,
plus durable scheduler terminal provenance. The analyzer deliberately refuses
to run without `terminal_provenance.json` proving `COMPLETED/0:0`, the exact
submitted script hash, and both protected submission and runner receipts for
every task.

Select at most five exact task IDs from the plan per dispatch. First run
`dispatch-eval ... --dry-run`; actual submission uses the same command with
`--confirm-study-id verifier-defect-withdrawal-v1` from the protected control
pane. Use `reconcile-eval` only for an ambiguous `sbatch` outcome and its exact
immutable intent. After all successful runner receipts exist, run:

```bash
uv run --no-sync user/tianhaowu/rsci/dispatch_defect_withdrawal.py \
  materialize-eval-terminals --plan "$EVAL_ROOT/plans/PLAN_ID/plan.json" \
  --confirm-study-id verifier-defect-withdrawal-v1
```

This replays every protected intent and submission receipt before writing any
terminal artifact, then binds the successful allocation's exact script,
`COMPLETED/0:0`, and `Restarts=0`.

## Validate and analyze

Each successful runner receipt binds the plan, checkpoint and config hashes,
scheduler identity, predecessor receipt, and these five replayable artifacts:

- `generation_manifest.json`;
- `generation_completion.json`;
- `generations.jsonl`;
- `strict_results.jsonl`;
- `metrics.json`.

After protected terminal provenance exists:

```bash
uv run --no-sync user/tianhaowu/rsci/materialize_defect_withdrawal_eval.py \
  validate-plan --plan "$EVAL_ROOT/plans/PLAN_ID/plan.json" --require-complete
uv run --no-sync user/tianhaowu/rsci/analyze_defect_withdrawal_eval.py analyze \
  --plan "$EVAL_ROOT/plans/PLAN_ID/plan.json"
uv run --no-sync user/tianhaowu/rsci/analyze_defect_withdrawal_eval.py validate \
  --analysis "$EVAL_ROOT/plans/PLAN_ID/analysis.json"
```

The analyzer independently re-scores every generation, classifies strict (S),
answer-correct/strict-wrong (A), and answer-wrong (W), and emits complete 3-by-3
source-to-endpoint transition matrices. OP21--40 is primary, OP41--45 is
secondary, and OP11--20 plus OP11--45 are also reported. These are paired
held-out response transitions, not literal training-trajectory lineages.
