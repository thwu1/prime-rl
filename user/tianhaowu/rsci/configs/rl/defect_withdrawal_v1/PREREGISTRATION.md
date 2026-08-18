# Defect-withdrawal v1

Status: exploratory smoke, no continuation outcomes inspected.

## Question

Does behavior \(A=\) answer-correct/strict-dependency-graph-wrong continue to
refresh after the false-positive verifier defect is removed, or does every
generation of reinforcement require another defect coin?

This is a gate for the absorbing-state hypothesis in
`VERIFIER_DEFECT_RESEARCH.md`, not a phase-transition or lineage-identification
test.

## Fixed source

The source checkpoint is optimizer step 4000 from the existing matched-age
OP10--40 runs:

- p5 source:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/rl/base-op10-40-strict-r128-defect-answer-p05-eval11-45-v2`
- p0 source:
  `/checkpoint/ram-h100-2/tianhaowu/rsci/rl/base-op10-40-strict-r128-defect-answer-p00-eval11-45-v2`

Step 4000 was chosen after observing the existing evaluation screen, so this
stage is exploratory. It is permanently retained by the source
`keep_interval=100` policy and provides matched p0/p5 optimizer age. The
existing asynchronous source evaluation gives:

| Source | OP21--40 strict | OP21--40 A | OP41--45 strict | OP41--45 A |
| --- | ---: | ---: | ---: | ---: |
| p5 step 4000 | 26/4000 | 603/4000 | 0/1000 | 169/1000 |
| p0 step 4000 | 50/4000 | 447/4000 | 0/1000 | 94/1000 |

Those rows can mix adjacent policy versions. They qualify the source only; a
standalone single-policy evaluation is required before a confirmatory claim.
The materializer independently replays these counts and binds every source
checkpoint and evaluation file.

The source jobs predate the commit-pinned launch workflow: they have resolved
configs and an `rl.sbatch`, but no `source_snapshot` or
`source_provenance.json`. The fork manifest binds those observable source
artifacts and bytes, but cannot retrospectively prove the implementation bytes
that generated them. Any promoted confirmation must create its high-A source
from a sealed launch.

## Smoke arms

All active arms resume full model, Adam, scheduler, trainer progress, and
orchestrator counters from step 4000. The newly started processes do not
restore historical RNGs, in-flight work, partial groups, environment state, or
W&B identity. `TrainSource` also does not checkpoint its cursor and restarts its
hard-coded seed-42 permutation at position zero. To avoid replaying the original
training prefix, all arms instead use one immutable continuation pool containing
only original OP10--40 rows absent from every shipped optimizer batch at source
steps 0--3999 in both p0 and p5. The pool materializer replays that exclusion
from all saved source trajectories and proves prompt identity against the
original 31k dataset. All arms start the same seed-42 permutation over this
fresh-gradient pool and use inference seed 20260811. This fixes a common task
order, not a common optimizer-clock prefix: reward-dependent filtering can make
the arms consume different numbers of tasks per update.

The pre-outcome audit finds 23,222 excluded indices and 7,778 gradient-unseen
rows. OP10 is the limiting stratum with 147 rows, so the largest exactly
OP-balanced pool is fixed at 147 rows per operation, 4,557 total. This is 2,993
rows above the predeclared minimum of \(375\times4+64=1{,}564\), but the minimum
does not bound extra finalized groups caused by filtering. Over every historical
375-update source window plus 64 open groups, the observed upper bounds are
4,000 task pulls for p0 and 1,821 for p5, leaving at least 557 rows of empirical
headroom. This is evidence, not a guarantee. The continuation therefore sets
`train_source_max_epochs=1`, which aborts before reshuffling after row 4,557;
the saved group ledger independently must contain no repeated `task_idx`. The
materialized sidecar binds the full per-operation capacity vector and combined
exclusion digest. The cursor and epoch count are not checkpointed, so a
scheduler requeue, process restart, or relaunch invalidates the arm; protected
terminal provenance must prove one uninterrupted attempt.

Selection is fixed before outcomes. Within each operation, the 147 seats are
allocated across `(template, mode)` strata by Hamilton largest remainder:
\(q_s=\lfloor147n_s/N_{op}\rfloor\), with residual seats assigned by descending
remainder and lexicographic `(template, mode)` ties. Rows within a stratum are
ranked by SHA-256 of the ASCII domain
`defect-withdrawal-v1-gradient-unseen-step4000-hash-rank-v1\0` followed by the
UTF-8 original ID; ties use original ID then source row index. This preserves
the available stratum mix without inheriting the source file's block order.
The precommitted combined-exclusion, p0/p5-overlap, and selected-index digests
are respectively `e79c4adfdbe634c633ba121cc5f560d64cd3a2bfbb66382c586e14e74efdfbfb`,
`b95c81bf4b637e0e56c54e4fe67f856b77acf22eb7c25ab5040dbade4be92c50`,
and `de04928fa4a114691d78402f6860eb8142e70530cdaf5d2d510cc08ce9b9bc4c`;
materialization fails if any differ.

| Arm | Source | Continuation reward |
| --- | --- | --- |
| ON | p5 step 4000 | behavior-A false positives at p=0.05 |
| OFF | p5 step 4000 | strict reward, p=0 |
| CLEAN | p0 step 4000 | strict reward, p=0 |
| FROZEN | p5 step 4000 | no training; standalone evaluation only |

The continuation contract is explicit: only answer-correct/strict-wrong
trajectories are defect-eligible; each eligible trajectory receives its own
deterministic coin; there are no false negatives, gates, behavior taxes, or
per-operation rates; and clean strict reward has weight one.

The active smoke ends at optimizer step 4375, 375 new updates. Checkpoints are
written every 25 steps and the 250-step retention interval preserves the exact
step-4250 intermediate readout. It records every pre-filter group and batch
attempt. Raw attempted/finalized group counts are mechanism diagnostics; resume
does not restore the historical finalized-group counter, so no raw target is
described as exact continuation of the source.
Inline OP11--45 evaluations run every 125 steps. The modulo schedule also fires
at resumed step 4000; it is a useful frozen-source monitor, but the dispatcher
can already have train requests in flight. All inline evaluations remain
monitoring signals because they can mix adjacent versions. Scientific endpoints
require standalone evaluation of the exact step-4000, step-4250, and step-4375
weights. The standalone base seed is 20260807; each request seed is the SHA-256
derivation
`int.from_bytes(SHA256(f"{base}:{op}:{id}:{row}:{rank}")[:8], "big") %
(2**63 - 1)` and is identical across checkpoints. Across the fixed 7,000
OP11--45 prompts, the dataset-bundle, prompt-sequence, and seed-sequence hashes
are respectively `369435fab4e74241e2112fe1c6fefc41d537febf1d0bbbdff40de1a1429809ce`,
`42954277948a8d6455250d90a36fc4aab322c200717996920ade5995cc170299`,
and `5d1b58ef75f1160dee4694c7416575e2f20f968963c89c91df73746c38502c6b`;
all 7,000 request seeds are unique. The eight byte-distinct model readouts are
p5 step 4000 once, p0 step 4000 once, and ON/OFF/CLEAN at steps 4250 and 4375.
The single p5 step-4000 result is the FROZEN counterfactual at both later clocks;
duplicating identical weights and seeds is not an independent observation.
Temperature is 0.7, top-p is 1.0, top-k is -1, maximum output length is 2,048,
the stop string is `</answer>`, and special-token stripping is disabled. The
complete content-addressed contract and provenance gates are specified in
`EVALUATION_RUNBOOK.md`; its canonical evaluation authority must be
materialized before any continuation outcome exists.

## Interpretation

Primary readouts on OP21--40 are strict prevalence, A prevalence, answer-wrong
prevalence, and source-to-endpoint transitions among those three categories.
OP41--45 is secondary and cannot establish a strict ceiling while strict
success remains zero.

At both post-fork step 4250 and 4375, report:

- OFF minus FROZEN new-A incidence and net A change;
- OFF minus CLEAN A prevalence;
- OFF minus ON A and strict prevalence;
- optimized proxy reward, strict reward, A candidates and triggers;
- attempted/finalized groups, shipped updates, trainable rows, truncation,
  entropy, mismatch KL, gradient norm, and update throughput.

For a band of \(N\) paired prompts, new-A incidence is
\((S\rightarrow A+W\rightarrow A)/N\), A-loss incidence is
\((A\rightarrow S+A\rightarrow W)/N\), and net A change is their difference.
An informative hard clean group is a finalized OFF group from OP21--40 whose
advantage population contains both strict rewards zero and one.

The optimizer-clock smoke is promoted only if all of the following hold on
primary OP21--40 at both steps 4250 and 4375:

1. OFF new-A incidence exceeds the identity FROZEN transition by more than 2
   percentage points;
2. OFF A prevalence is no more than 2 points below FROZEN A prevalence;
3. OFF A prevalence exceeds CLEAN by more than 3 points;
4. ON and OFF differ by less than 2 points in both A and strict prevalence;
5. at step 4250, OFF has at least 250 cumulative informative hard clean groups,
   every arm has shipped exactly 250 new updates, and no task has repeated; at
   step 4375 the corresponding thresholds are 375 groups and 375 updates, with
   no repeat over the full continuation.

A plateau with no new-A excess is passive parameter persistence, not autonomous
propagation. Any failed exposure, completion, or no-wrap condition makes the
screen inconclusive.

OFF deliberately resumes the p5 Adam state. Its first-moment transient and
second-moment geometry can sustain post-withdrawal movement even if behavior A
does not reproduce itself. A positive screen therefore establishes
p-independent state continuation, not autonomous behavioral lineage. Promotion
must add a p5-weights/fresh-optimizer flush arm, alongside the full-state arm,
before attributing the effect to model behavior rather than optimizer memory.

No p-value or treatment-variance claim is made from this one continuation
block. A positive screen promotes a six-block, ON/OFF-counterbalanced
confirmation that preregisters the same numerical margins at matched raw and
optimizer clocks. A negative screen is descriptive unless OFF loses more than
2 points of A while ON stays within 2 points of FROZEN at both optimizer
readouts. Every other outcome is inconclusive.

## Launch gate

Before any submission:

1. create the commit-pinned evaluation control snapshot and materialize the
   canonical `evaluation_authority.json` from `EVALUATION_RUNBOOK.md`;
2. materialize and independently validate the shared fresh-gradient
   continuation pool;
3. materialize and validate each independent checkpoint seed copy;
4. create each run-local commit-pinned source snapshot;
5. materialize and seal the resolved base/common/arm config composition;
6. before submission, run the manifest validator from that snapshot with
   `--require-pristine`; the runtime pre-run repeats ordinary hash validation
   after Slurm has necessarily created its job log and log-directory skeleton;
7. confirm no source or destination hashes changed;
8. materialize the training dispatch authority before any withdrawal scheduler
   job exists, then validate its content-addressed global, batch, and per-arm
   intent chain;
9. require the live resource gate to be open, reject any live selected job
   name, and submit only through the protected control tmux with inherited
   `SBATCH_*` variables removed;
10. accept an endpoint only when `sacct` proves `COMPLETED/0:0`, `Restarts=0`,
    the exact submitted script, and the immutable ledger replay proves exact
    optimizer steps and no repeated continuation task.

The smoke is lower priority than the fixed-clock/Gstar jobs, the frozen
known-cost study, and any legacy `rsci-rl-op10-40-*` allocation. No withdrawal
job may be submitted while that resource-policy gate is closed.
