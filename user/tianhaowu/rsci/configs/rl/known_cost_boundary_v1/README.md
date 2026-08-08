# Known-cost boundary pilot

This directory contains the frozen 30-arm exploratory pilot described in
`PREREGISTRATION.md`. No RL arm may be submitted until the tag-kernel decision
gate and all deterministic data/config preflights pass.

Resolve one arm from left to right:

1. `../op10_40_strict_grpo_r128_defect_p00.toml`;
2. `common.toml`;
3. exactly one `b<seed>_<condition>.toml` overlay.

The three blocks are fixed as follows:

| Block seed | Selected tags | Training bank |
| ---: | --- | --- |
| `20260808` | `{0,1}` | `.../known-cost-boundary-v1/block-20260808/train.jsonl` |
| `20260809` | `{2,3}` | `.../known-cost-boundary-v1/block-20260809/train.jsonl` |
| `20260810` | `{4,5}` | `.../known-cost-boundary-v1/block-20260810/train.jsonl` |

Each block has `clean`, `tax`, four hidden-group (`g`) doses, and four
persistent-tag (`t`) doses. The dose labels `p0075`, `p0125`, `p0225`, and
`p0375` mean marginal candidate false-positive probabilities 0.75%, 1.25%,
2.25%, and 3.75%. All non-clean arms use `c0=0.03`; `tax` has `p=0` and
`clean` has both `p=0` and `c0=0`.

Materialize and validate each tagged bank with the commit-pinned source before
sealing launches:

```bash
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_tagged_bank.py materialize \
  --output /checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/known-cost-boundary-v1/block-20260808/train.jsonl \
  --block-seed 20260808 \
  --tokenizer /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_tagged_bank.py validate \
  --manifest /checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/known-cost-boundary-v1/block-20260808/train.jsonl.manifest.json \
  --tokenizer /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base
```

Repeat with seeds `20260809` and `20260810`. Existing outputs are immutable:
the materializer accepts a repeated invocation only when bytes and manifest
match exactly. `--tokenizer` is mandatory for production even though it is an
optional CLI argument; reject a manifest whose `tag_tokenization` is null.

For an eligible arm, create, resolve, and seal the immutable runtime:

```bash
RUN_DIR=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1/block-20260808/g-p0125
SOURCE_COMMIT=$(git rev-parse HEAD)
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create \
  "$RUN_DIR" --commit "$SOURCE_COMMIT"
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" materialize-launch \
  "$RUN_DIR" \
  user/tianhaowu/rsci/configs/rl/op10_40_strict_grpo_r128_defect_p00.toml \
  user/tianhaowu/rsci/configs/rl/known_cost_boundary_v1/common.toml \
  user/tianhaowu/rsci/configs/rl/known_cost_boundary_v1/b20260808_g_p0125.toml
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" seal-launch \
  "$RUN_DIR"
```

The v2 kernel gate decides which configs are eligible. If analytic median
off-diagonal transfer is at most 0.5 and the preregistered finite-step ordering
check passes, the full 30-arm pilot is eligible. Otherwise only `g_p0125`,
`t_p0125`, `g_p0375`, and `t_p0375` in block `20260808` are eligible for the
smoke screen. The ordering check uses a `0.02` normalized analytic separation,
requires at least five resolvable target pairs per source tag, and permits no
finite-step inversions.

Every arm requests five eight-GPU nodes. Submit sealed `rl.sbatch` files only
through the protected control tmux and never admit more than five arms under
the 200-GPU group limit. Do not submit this pilot while the fixed-clock SFT or
Gstar studies remain quota-pending.

## Protected dispatch

The kernel receipt retains the original read-only finalizer snapshot. The
launch materializer, enforcing Stage-1 dispatcher, post-run consumers, and
evaluation planner run from one successor commit-pinned snapshot. Before the
launch intent, materialize one immutable kernel-finalizer reconciliation. It
statically invokes the exact historical finalizer, exact-matches retained
GPU/validator terminal `sacct` fields while taking submitted-script provenance
only from the receipt and pre-execution witness, and binds finalizer job
`10281828`, its nonempty read-only submitted-script capture made directly
within the controller retention window, and its exact allocation log. Launch
materialization and every later validation replay that sidecar
statically, so controller batch-script and accounting retention are no longer
durability dependencies.

```bash
SUCCESSOR_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-postrun-control-plane-v4
SUCCESSOR_COMMIT=<pushed-successor-commit>
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create \
  "$SUCCESSOR_ROOT" --commit "$SUCCESSOR_COMMIT"
uv run --no-sync "$SUCCESSOR_ROOT/source_snapshot/user/tianhaowu/rsci/source_provenance.py" verify-source \
  "$SUCCESSOR_ROOT"
source "$SUCCESSOR_ROOT/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh" "$SUCCESSOR_ROOT"
RUN_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1
DISPATCH_STATE=/checkpoint/ram-h100-2/tianhaowu/rsci/dispatch/verifier-defect-known-cost-boundary-v1
KERNEL_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-tag-kernel-v2
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py materialize-reconciliation \
  --kernel-root "$KERNEL_ROOT"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py validate-reconciliation \
  --reconciliation "$KERNEL_ROOT/kernel_finalizer_reconciliation_v2.json"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py materialize \
  --run-root "$RUN_ROOT" \
  --preflight-report /checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-boundary-preflight-v1/report.json \
  --kernel-root "$KERNEL_ROOT" \
  --kernel-reconciliation "$KERNEL_ROOT/kernel_finalizer_reconciliation_v2.json" \
  --tokenizer /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py validate \
  --intent "$RUN_ROOT/submission_intent.json" \
  --tokenizer /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base
```

Before any eligible arm starts, use that same successor snapshot to materialize
the branch-agnostic analysis/eval authority under the Stage-1 dispatch lock:

```bash
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_postrun_authority.py materialize \
  --initial-intent "$RUN_ROOT/submission_intent.json" \
  --control-root "$SUCCESSOR_ROOT"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_postrun_authority.py validate \
  --authority "$RUN_ROOT/postrun_authority.json"
```

Create and verify this snapshot before the authority performs its zero-job
pre-RL scan. `SUCCESSOR_COMMIT` must be the pushed commit containing every
post-run consumer and dispatcher used below; an existing mutable checkout is
not a substitute.

This authority accepts exactly the kernel-selected full-30 or smoke-4 branch,
replays the intent with its historical validator, checks all 30 frozen job
names and output directories have no scheduler/start evidence, and pins the
training replay, training readout consumer, completion-receipt materializer,
the exact sidecar-enforcing Stage-1 dispatcher, historical planner, result
analyzer, eval runner, and eval dispatcher. The Stage-1 dispatcher, analyzer,
and eval dispatcher fail closed
without this adjacent artifact. For a smoke-4 decision, freeze the append-only
promotion authority under the same lock before Stage-1 dispatch:

```bash
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promotion.py materialize-authority \
  --initial-intent "$RUN_ROOT/submission_intent.json" \
  --control-root "$SUCCESSOR_ROOT"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promotion.py validate-authority \
  --authority "$RUN_ROOT/promotion_authority.json"
```

The promotion command is smoke-only. It freezes the exact remaining 26 arms
and the four-clock spending rule; it does not submit anything. Keep the
post-run snapshot active for the commands below. The exact dispatcher recorded
by the launch intent validates the mandatory post-run sidecar and, for smoke-4,
the promotion sidecar under the Stage-1 lock. It binds both sidecar identities
through the scheduler comment and immutable global, batch, arm, and receipt
chain.

The finalized `submission_intent.json` remains the sole arm and scheduler
allowlist; the adjacent sidecars are mandatory study-validity preconditions.
Never invoke a byte-different dispatcher or an arm's sealed `rl.sbatch`
directly. Preview one to five explicit eligible arm filenames from the same
activated successor shell:

```bash
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_boundary.py dispatch \
  --intent "$RUN_ROOT/submission_intent.json" \
  --state-root "$DISPATCH_STATE" \
  --arm b20260808_g_p0125.toml \
  --dry-run
```

Dry-run is read-only. It queries Slurm and prints the exact command, the
content-addressed comment, the sealed account, the authority-pinned
`--qos=h100_ram_high`, and the projected study-wide live count. The state
root must exactly equal the external path frozen in the launch authority; its
shared lock serializes every dispatch and reconciliation. Add another
`--arm <exact-filename>` for each additional arm, up to five.

Actual dispatch must run in the launch intent's recorded control tmux and
requires exact study confirmation:

```bash
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_boundary.py dispatch \
  --intent "$RUN_ROOT/submission_intent.json" \
  --state-root "$DISPATCH_STATE" \
  --arm b20260808_g_p0125.toml \
  --confirm-study-id verifier-defect-known-cost-boundary-v1
```

The dispatcher strips every inherited `SBATCH_*` variable and executes only
`env -u SBATCH_OUTPUT -u SBATCH_ERROR sbatch --parsable
--comment=<content-hash> --qos=h100_ram_high --account=<sealed-account>
<sealed-sbatch>`. The explicit flags are required because this cluster's
`sbatch` does not implement an `SBATCH_COMMENT` environment override.
It writes immutable global, batch, and per-arm intents before `sbatch`, and an
atomic receipt only after the returned job has the exact scheduler identity.
It rejects excluded arms, repeated arm names, existing receipts, runtime start
artifacts, scheduler duplicates, and any call that would raise the study above
five live protected jobs. A prelaunch `STATUS.md` is allowed; job logs, W&B,
weights, checkpoints, and runtime log directories prove that an arm started.

If `sbatch` or its identity check has an ambiguous outcome, all later dispatch
is blocked. Reconcile only by the arm's exact content-addressed Slurm comment:

```bash
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_boundary.py reconcile \
  --intent "$RUN_ROOT/submission_intent.json" \
  --state-root "$DISPATCH_STATE" \
  --arm b20260808_g_p0125.toml \
  --dry-run
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_boundary.py reconcile \
  --intent "$RUN_ROOT/submission_intent.json" \
  --state-root "$DISPATCH_STATE" \
  --arm b20260808_g_p0125.toml \
  --confirm-study-id verifier-defect-known-cost-boundary-v1
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_boundary.py status \
  --intent "$RUN_ROOT/submission_intent.json" \
  --state-root "$DISPATCH_STATE"
```

Zero matches remain unresolved; multiple exact matches fail closed. Do not
delete or rewrite an unresolved intent and do not resubmit that arm.

## Immutable held-out evaluation plan

After each Stage-1 RL allocation is terminal, materialize and replay its
write-once completion receipt from the post-run snapshot:

```bash
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_training_completion.py materialize \
  --initial-intent "$RUN_ROOT/submission_intent.json" \
  --state-root "$DISPATCH_STATE" \
  --arm b20260808_g_p0125.toml \
  --run-dir /checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1/block-20260808/g-p0125
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_training_completion.py validate \
  --receipt /checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1/block-20260808/g-p0125/training_completion_receipt.json \
  --recheck-live-scheduler
```

The receipt chains the protected submission job to exact terminal
`COMPLETED/0:0` accounting, allocation stdout/stderr, clean orchestrator
markers, local event streams, ledgers, resolved configs, and the final stable
checkpoint. It does not claim a trainer exit record or scientific metric
completeness; the deterministic training consumer establishes those separately.

After every eligible run has this receipt and its audit logs and retained
checkpoints are immutable, describe the exact run set in a JSON request:

```json
{
  "artifact_type": "rsci_known_cost_checkpoint_eval_request",
  "launch_intent": "/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1/submission_intent.json",
  "optimizer_step_targets": [375, 750, 1500],
  "raw_group_targets": [3000, 6000, 12000],
  "request_seed": 20260807,
  "schema_version": 1,
  "study_id": "verifier-defect-known-cost-boundary-v1",
  "tagged_data_dir": "/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/known-cost-boundary-v1/eval-tagged"
}
```

The launch intent is required and authoritative: the planner independently
replays its preflight, kernel decision, source seals, and exact eligible-run
inventory. It also requires the same read-only, commit- and environment-pinned
control-plane snapshot used to finalize the kernel receipt and launch intent;
the activation above must still be active. Arbitrary run lists and subsets are
not accepted. Materialize and independently replay the plan with:

```bash
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_eval_plan.py materialize \
  --spec /absolute/path/known_cost_eval_request.json \
  --eval-root /checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-known-cost-boundary-v1
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_eval_plan.py validate \
  --plan /checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-known-cost-boundary-v1/plans/PLAN_ID/plan.json
```

The planner has no submission command. It hashes the resolved training
configs, audit logs, selected checkpoint byte inventories, evaluator and
strict scorer, all 35 untagged shards, all 35 tagged shards and adjacent
sidecars, imported tag/evaluator constants, and the exact tokenizer used to
establish equal 13-token tags. It refuses a missing, extra, ineligible, or
runtime-identity-mismatched arm relative to the launch intent. Each
unique model task receives one untagged and six tagged OP11--45 configs. The
inference server is explicitly pinned to that certified tokenizer rather than
any tokenizer files copied into a retained checkpoint. The
six tagged configs use `paired_source_v1`, so every source prompt receives the
same request seed under all six tags and at every checkpoint. The untagged
view deliberately retains the legacy seed derivation for comparability.

Optimizer targets require exact checkpoints. A raw-group target either maps
to one unique exact checkpoint or to two retained endpoints that bracket it;
both endpoints are evaluated and later interpolated on the raw-group axis.
Neither endpoint may be renamed as the target. Multiple exact checkpoints at
one raw exposure are treated as ambiguous and fail closed. Step 0 is one
shared task across all arms, while nonzero checkpoint tasks remain
run-specific. The planner accepts any retained bracket step through 1500 and
does not use or modify the legacy `{0,25,...,500}` evaluator.

Every plan lives below `plans/<plan-id>/`, with disjoint per-model result
roots. Immutable terminal receipts use
`receipts/<task-id>/attempt_NNNN.json`. Retries must be contiguous, bind the
SHA-256 of the previous failed/cancelled/preempted receipt, and reuse the
sealed output roots so the evaluator's generation-manifest resume checks stay
authoritative. A successful receipt inventories all five completion artifacts
for all seven shards; no retry may follow success. `validate` replays the
entire plan and any receipts from their source artifacts.

## Protected evaluation execution and analysis

The plan remains owned by the historical planner, but execution and analysis
run from `SUCCESSOR_ROOT`. Reactivate that snapshot, choose one to five explicit
incomplete task IDs from the immutable plan, and preview the exact one-H100
jobs:

```bash
PLAN=/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-known-cost-boundary-v1/plans/PLAN_ID/plan.json
EVAL_STATE=/checkpoint/ram-h100-2/tianhaowu/rsci/dispatch/verifier-defect-known-cost-boundary-eval-v1/PLAN_ID
source "$SUCCESSOR_ROOT/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh" "$SUCCESSOR_ROOT"
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_eval.py dispatch \
  --plan "$PLAN" --state-root "$EVAL_STATE" \
  --task MODEL_TASK_ID --dry-run
```

Actual dispatch requires the recorded control tmux and
`--confirm-study-id verifier-defect-known-cost-boundary-v1`. The dispatcher
uses explicit Slurm comment/QoS/account fields, removes every ambient
`SBATCH_*` variable, and enforces five live evaluation jobs across every plan
for this study. Each task runs one inference server and its seven shards
sequentially, resuming only shards whose five completion artifacts do not
already validate. If a scheduler-terminal hard failure leaves no runner
receipt, use `terminalize --dry-run` and then the confirmed `terminalize`
command; it can create only a failed/cancelled/preempted receipt, never a
success.

After every plan task's latest receipt has validated as succeeded, capture the
live terminal allocation and submitted batch-script evidence exactly once,
then replay it without Slurm:

```bash
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_eval.py materialize-terminals \
  --plan "$PLAN" --state-root "$EVAL_STATE" \
  --confirm-study-id verifier-defect-known-cost-boundary-v1
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_eval.py validate-terminals \
  --plan "$PLAN"
# Optional only while Slurm still retains every allocation and submitted script:
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_eval.py validate-terminals \
  --plan "$PLAN" --live-recheck
```

`materialize-terminals` writes the read-only, self-hashed
`$(dirname "$PLAN")/terminal_provenance.json`. It refuses a partial or
retryable plan. Ordinary validation and analysis use only that artifact plus
the immutable plan, dispatch intents, submission receipts, attempt receipts,
and batch-script files; scheduler retention is no longer required. The smoke
plan and any promoted-26 successor plan each require their own plan-local
terminal provenance artifact under this same contract.

After offline terminal replay passes, build and replay the single immutable
result artifact:

```bash
uv run --no-sync user/tianhaowu/rsci/analyze_known_cost_boundary_results.py analyze \
  --plan "$PLAN"
uv run --no-sync user/tianhaowu/rsci/analyze_known_cost_boundary_results.py validate \
  --analysis "$(dirname "$PLAN")/analysis/known_cost_boundary_results.json"
```

The result consumer validates the historical planner and launch validator at
their recorded paths, the adjacent post-run authority, every terminal receipt,
every strict generation/scoring artifact, and the deterministic training
audit. Raw-group strict outcomes use the plan's recorded sourcewise bracket
interpolation; endpoints stay visible. The smoke promotion decision is read
from unrounded same-source OP21--40 A-localization contrasts and cannot mix
doses across its four required clocks. Its output remains a descriptive,
model-conditional finite-time screen: it does not license phase-transition,
hysteresis, causal treatment-effect, or final-ceiling claims.

## Smoke-pass Stage-2 and combined 30-arm result

Run this section only when the immutable smoke analysis says
`proceed_to_full_grid=true`. The Stage-2 intent replays that analysis and
requires one fixed dose to pass all four spending clocks; it cannot combine
clock passes across doses. Materialize the exact remaining-26 intent:

```bash
SMOKE_ANALYSIS="$(dirname "$PLAN")/analysis/known_cost_boundary_results.json"
STAGE2_STATE=/checkpoint/ram-h100-2/tianhaowu/rsci/dispatch/verifier-defect-known-cost-boundary-v1-stage2
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promotion.py materialize-stage2 \
  --authority "$RUN_ROOT/promotion_authority.json" \
  --analysis "$SMOKE_ANALYSIS"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promotion.py validate-stage2 \
  --intent "$RUN_ROOT/stage2_submission_intent.json"
```

Preview and submit one to five explicit filenames from the intent's ordered
`remaining_arm_filenames`. Actual dispatch must run in the recorded control
tmux; the same five-live-arm cap covers all 30 study job names:

```bash
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_promotion.py dispatch \
  --intent "$RUN_ROOT/stage2_submission_intent.json" --state-root "$STAGE2_STATE" \
  --arm b20260809_clean.toml --dry-run
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_promotion.py dispatch \
  --intent "$RUN_ROOT/stage2_submission_intent.json" --state-root "$STAGE2_STATE" \
  --arm b20260809_clean.toml \
  --confirm-study-id verifier-defect-known-cost-boundary-v1
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_promotion.py status \
  --intent "$RUN_ROOT/stage2_submission_intent.json" --state-root "$STAGE2_STATE"
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_promotion.py reconcile \
  --intent "$RUN_ROOT/stage2_submission_intent.json" --state-root "$STAGE2_STATE" \
  --arm b20260809_clean.toml --dry-run
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_promotion.py reconcile \
  --intent "$RUN_ROOT/stage2_submission_intent.json" --state-root "$STAGE2_STATE" \
  --arm b20260809_clean.toml \
  --confirm-study-id verifier-defect-known-cost-boundary-v1
```

For an ambiguous submission, use `reconcile --dry-run` and then the same
`reconcile` command with the study confirmation; never resubmit the arm
directly. After each promoted allocation is terminal, create its distinct
Stage-2 completion receipt. It is not interchangeable with the Stage-1
`training_completion_receipt.json`:

```bash
STAGE2_RUN="$RUN_ROOT/block-20260809/clean"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py materialize-stage2-completion \
  --promotion-authority "$RUN_ROOT/promotion_authority.json" \
  --stage2-intent "$RUN_ROOT/stage2_submission_intent.json" \
  --arm b20260809_clean.toml --run-dir "$STAGE2_RUN"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py validate-stage2-completion \
  --receipt "$STAGE2_RUN/stage2_training_completion_receipt.json" \
  --recheck-live-scheduler
```

Repeat for every exact promoted arm. Once all 26 protected submission and
completion receipts exist, seal the append-only evaluation authority:

```bash
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py materialize-authority \
  --postrun-authority "$RUN_ROOT/postrun_authority.json" \
  --promotion-authority "$RUN_ROOT/promotion_authority.json" \
  --stage2-intent "$RUN_ROOT/stage2_submission_intent.json"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py validate-authority \
  --authority "$RUN_ROOT/promoted_eval_authority.json"
```

Write `/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-known-cost-boundary-v1/promoted_eval_request.json`
with these exact fields:

```json
{
  "artifact_type": "rsci_known_cost_promoted_checkpoint_eval_request",
  "optimizer_step_targets": [375, 750, 1500],
  "promoted_eval_authority": "/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1/promoted_eval_authority.json",
  "raw_group_targets": [3000, 6000, 12000],
  "request_seed": 20260807,
  "schema_version": 1,
  "study_id": "verifier-defect-known-cost-boundary-v1",
  "tagged_data_dir": "/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/known-cost-boundary-v1/eval-tagged"
}
```

Materialize the second plan and take its exact path from the command output:

```bash
EVAL_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-known-cost-boundary-v1
PROMOTED_SPEC="$EVAL_ROOT/promoted_eval_request.json"
PROMOTED_PLAN=$(uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py materialize-plan \
  --spec "$PROMOTED_SPEC" --eval-root "$EVAL_ROOT" | jq -r .plan_path)
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py validate-plan \
  --plan "$PROMOTED_PLAN"
PROMOTED_PLAN_ID=$(jq -r .plan_id "$PROMOTED_PLAN")
PROMOTED_EVAL_STATE="/checkpoint/ram-h100-2/tianhaowu/rsci/dispatch/verifier-defect-known-cost-boundary-eval-v1/$PROMOTED_PLAN_ID"
PROMOTED_TASK_ID=$(jq -r '.tasks[0].task_id' "$PROMOTED_PLAN")
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_eval.py dispatch \
  --plan "$PROMOTED_PLAN" --state-root "$PROMOTED_EVAL_STATE" \
  --task "$PROMOTED_TASK_ID" --dry-run
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_eval.py dispatch \
  --plan "$PROMOTED_PLAN" --state-root "$PROMOTED_EVAL_STATE" \
  --task "$PROMOTED_TASK_ID" \
  --confirm-study-id verifier-defect-known-cost-boundary-v1
```

Dispatch explicit incomplete task IDs in batches of at most five using the
same command with the study confirmation. After every latest task attempt is
`succeeded`, freeze and validate this plan's terminal provenance before any
scientific analysis:

```bash
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_eval.py materialize-terminals \
  --plan "$PROMOTED_PLAN" --state-root "$PROMOTED_EVAL_STATE" \
  --confirm-study-id verifier-defect-known-cost-boundary-v1
uv run --no-sync user/tianhaowu/rsci/dispatch_known_cost_eval.py validate-terminals \
  --plan "$PROMOTED_PLAN"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py analyze-promoted \
  --plan "$PROMOTED_PLAN"
PROMOTED_ANALYSIS="$(dirname "$PROMOTED_PLAN")/analysis/promoted_results.json"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py validate-promoted \
  --analysis "$PROMOTED_ANALYSIS"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py combine \
  --smoke-analysis "$SMOKE_ANALYSIS" --promoted-analysis "$PROMOTED_ANALYSIS"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py validate-combined \
  --analysis "$(dirname "$PROMOTED_PLAN")/analysis/combined_results.json"
```

The promoted result contains the 26-arm strict held-out readouts, durable eval
terminal provenance, and exact training mechanism/stability diagnostics. The
combined artifact joins those with the immutable smoke four into the complete
30-arm, six-clock descriptive grid without rewriting either partition. It
remains an exploratory finite-time result and does not establish a phase
transition, hysteresis, causal effect, or asymptotic ceiling.
