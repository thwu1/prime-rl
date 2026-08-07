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

The kernel finalizer, launch materializer, dispatcher, and evaluation planner
must all run from the same read-only control-plane snapshot. After the kernel
job and validator complete, that snapshot builds a receipt which binds the
final scheduler envelope and re-queries both terminal Slurm records. Activate
it before materializing the launch intent or invoking any later control-plane
command:

```bash
CONTROL_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-control-plane-v1
source "$CONTROL_ROOT/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh" "$CONTROL_ROOT"
RUN_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1
DISPATCH_STATE=/checkpoint/ram-h100-2/tianhaowu/rsci/dispatch/verifier-defect-known-cost-boundary-v1
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py materialize \
  --run-root "$RUN_ROOT" \
  --preflight-report /checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-boundary-preflight-v1/report.json \
  --kernel-root /checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-tag-kernel-v2 \
  --tokenizer /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py validate \
  --intent "$RUN_ROOT/submission_intent.json" \
  --tokenizer /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base
```

The finalized `submission_intent.json` is the sole dispatch authority. Never
invoke an arm's sealed `rl.sbatch` directly. Preview one to five explicit
eligible arm filenames from the same activated shell:

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

After the eligible RL runs have stopped and their audit logs and retained
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
