# Checkpoint-wise known-cost tag kernel

This additive diagnostic measures the sealed 174-pair, six-tag gradient kernel
at a matched BF16-round-trip reference and at steps 375, 750, and 1,500 for
the four known-cost smoke arms. It cannot authorize training, evaluation, or
smoke promotion.

## Freeze the control source and plan

Commit every supplemental implementation before creating the source snapshot.
Use the exact commit, then activate only that read-only snapshot:

```bash
CONTROL=/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-checkpoint-kernel-control-v1
COMMIT=$(git rev-parse HEAD)
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create "$CONTROL" --commit "$COMMIT"
source "$CONTROL/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh" "$CONTROL"
```

The activation helper verifies the source tree, shared environment, lockfile,
pip freeze, and import locations. From that activated snapshot, freeze the
content-addressed 13-task plan before any checkpoint-kernel GPU execution:

```bash
RUN_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1
uv run --no-sync python user/tianhaowu/rsci/materialize_known_cost_checkpoint_kernel_plan.py materialize \
  --intent "$RUN_ROOT/submission_intent.json" \
  --postrun-authority "$RUN_ROOT/postrun_authority.json" \
  --promotion-authority "$RUN_ROOT/promotion_authority.json" \
  --control-root "$CONTROL"
```

The plan binds the frozen interpreter, environment, probe, readiness
materializer, runner, dispatcher, terminalizer, analyzer, documentation, and
all transitive probe dependencies. It records future checkpoint paths without
claiming hashes for files that do not yet exist.

Trained readiness deliberately replays the separately authority-pinned
post-run-v4 completion validator in its own snapshot environment. That
historical validation is isolated from the checkpoint-kernel snapshot rather
than inheriting its `PYTHONPATH` or RSCI runtime variables.

## Readiness and dispatch

Materialize readiness separately for each task after its input exists. The
step-0 reference is immediately eligible; trained tasks require the exact
adjacent training-completion receipt and a stable BF16 checkpoint:

```bash
PLAN=/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-checkpoint-kernel-v1/plans/PLAN_ID/plan.json
uv run --no-sync python user/tianhaowu/rsci/materialize_known_cost_checkpoint_kernel_readiness.py materialize \
  --plan "$PLAN" --task-id reference-step-0000
```

Inspect a dispatch without mutation:

```bash
READY="${PLAN%/plan.json}/readiness/reference-step-0000.json"
uv run --no-sync python user/tianhaowu/rsci/dispatch_known_cost_checkpoint_kernel.py dispatch \
  --plan "$PLAN" --readiness "$READY" --task-id reference-step-0000
```

Actual submission is permitted only in the protected `Launcher` tmux and only
when the fixed-clock/Gstar resource-policy gate is open. The dispatcher writes
an immutable pre-submit intent, submits the GPU held, submits its dependent CPU
terminalizer, freezes both scheduler observations and the submission receipt,
then releases the GPU and freezes a release receipt. The GPU runner waits for
and validates both receipts. It writes only an attempt-local candidate; a
successful terminalizer hard-links that candidate to the canonical output.

```bash
uv run --no-sync python user/tianhaowu/rsci/dispatch_known_cost_checkpoint_kernel.py dispatch \
  --plan "$PLAN" --readiness "$READY" --task-id reference-step-0000 \
  --submit --confirm-study-id verifier-defect-known-cost-boundary-v1
```

Technical retries require `--retry-failed` and bind the immediately preceding
failed terminal receipt. They are not scientific repeats.

## Seal and analyze the complete task set

Canonical files alone are never accepted as results. After all 13 primary
tasks succeed, freeze finalizer terminal accounting and then run the sealed
analysis:

```bash
uv run --no-sync python user/tianhaowu/rsci/analyze_known_cost_checkpoint_kernel.py materialize-terminals \
  --plan "$PLAN"
TERMINALS="${PLAN%/plan.json}/terminal_provenance.json"
uv run --no-sync python user/tianhaowu/rsci/analyze_known_cost_checkpoint_kernel.py analyze \
  --plan "$PLAN" --terminal-provenance "$TERMINALS"
```

The analyzer rejects partial or extra tasks, unterminated attempts, attempts
after success, unmatched candidate/canonical inodes, incomplete GPU or CPU
accounting, and any input TOCTOU change. It reconstructs every Gram matrix from
the analytic kernel and gradient norms, recomputes the finite localization
slope, and writes `analysis/primary_summary.json` plus the immutable
`repeat_decision.json`.

A primary qualifying pair is reported only as
`primary_pair_qualifies_pending_fresh_repeats`. Reproducible tenfold
amplification requires a separately preregistered, decision-bound repeat plan
and control snapshot created before any repeat output. The primary 13-task plan
does not authorize those jobs. Neither the primary result nor its repeats can
change smoke promotion.
