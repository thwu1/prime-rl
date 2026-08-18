# Correlated verifier-defect Stage 1b

This directory contains six launch overlays for the preregistered
prompt-random, non-legible group-gate (G-B) versus persistent template-gate
(T-B) comparison. They are
launch artifacts only: no run in this directory has been submitted. Scientific
estimands and decision rules are locked in
[PREREGISTRATION.md](PREREGISTRATION.md).

Resolve each run from left to right:

1. `../op10_40_strict_grpo_r128_defect_p00.toml`;
2. `common.toml`;
3. exactly one `s<seed>_<condition>.toml` overlay.

The scientific iid reference is the same seed's B, `L=128`, `p=0.0025` arm in
`../masked_activation_v1/`; it is not duplicated here. G and T keep all 128
physical slots eligible, use behavior recipients, optimize the proxy reward,
and retain clean strict reward as the target metric.

## Assignment law

The nominal per-candidate marginal is `p=0.0025`, the gate probability is
`alpha=1/3`, and the candidate coin conditional on an open gate is
`q=p/alpha=0.0075`.

- G hashes `(defect_seed, sample_id)` in the independent
  `defect-group-gate-v1` domain. A group opens when that draw is below
  `alpha`; candidate sample-slot coins are then compared with `q`.
- T opens every group from one selected visible GSM-Infinite template and
  closes the other two. The three-seed Latin square is
  `20260805 -> crazy_zootopia`,
  `20260806 -> movie_festival_awards`, and
  `20260807 -> teachers_in_school`. Across that randomized assignment, every
  template candidate has marginal `p`; within a realized T run, the intended
  risk is heterogeneous.

G and T therefore have the same randomized one-group law. They differ in
whether the gate is independent between prompts or persists on a visible,
learnable template. The runtime logs the mask, candidate and recipient vectors
unchanged from Stage 1. The gate multiplies behavior-trigger eligibility only,
so a later T-M overlay can reuse the existing minimum-behavior recipient rule
without changing G/T randomization.

Required replay metrics include `defect_gate_open_metric`,
`defect_gate_draw_metric`, `defect_gate_probability_metric`,
`defect_gate_eligible_metric`, nominal and conditional rates, gate mode,
observed template index, and selected-template index. Audit a completed run
with:

```bash
uv run --no-sync user/tianhaowu/rsci/analyze_masked_verifier_attempts.py \
  RUN_DIR --output RUN_DIR/analysis/correlated_attempts.json
```

The analyzer binds the resolved config, rollout audit streams, and training
dataset. It independently replays the group-gate hash, template lookup,
sample-slot coins, masks, B/S/M recipient vectors, rewards, raw batch-attempt
clock, and stopping contract.

The sealed step-zero calibration is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/correlated-defect-preflight-v2/report.json`
(SHA-256
`680c5bf3dd441a7b26da685532f60d3c04af3f69b422088bc25a89a50a263d9d`).
Its proportional 12,000-group hard contribution predicts 231.599 activated
G/T groups and 293.001 candidate rewards in expectation; those are calibration
targets, not on-policy outcome predictions. The v2 report separately replays
the exact deterministic candidate coins: one seed's realized paired ratio is
just outside the expected-exposure margin, while the pooled G/T ratios are
1.00498 for triggers and 1.00398 for activated groups. Seeds and rates were not
retuned.

## Launch preparation

After the runtime and overlays are committed, create one source snapshot per
run, materialize the three config paths above from that snapshot, and seal it
before submission. For example:

```bash
RUN_DIR=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-correlated-v1/seed-20260805/g-b-alpha1of3-p0025
SOURCE_COMMIT=$(git rev-parse HEAD)
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create \
  "$RUN_DIR" --commit "$SOURCE_COMMIT"
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" materialize-launch \
  "$RUN_DIR" \
  user/tianhaowu/rsci/configs/rl/op10_40_strict_grpo_r128_defect_p00.toml \
  user/tianhaowu/rsci/configs/rl/correlated_defect_v1/common.toml \
  user/tianhaowu/rsci/configs/rl/correlated_defect_v1/s20260805_g_b_a1of3_p0025.toml
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" seal-launch \
  "$RUN_DIR"
```

Do not submit from the live checkout or before the shared GPU resource gate is
cleared. Every arm retains the Stage-1 joint endpoint of at least 1,500 shipped
updates and 12,000 finalized groups at a retained 50-update checkpoint, with
hard guards at 3,000 updates and 20,000 groups. Asynchronous evaluation remains
disabled through the hard guard; use saved single-policy checkpoints for clean
strict OP11-45 evaluation.
