# Known-cost checkpoint-kernel supplemental preregistration

This supplemental analysis was specified before any known-cost boundary RL arm
was submitted. It does not change the frozen four-arm launch intent, reward,
data, optimizer, smoke-promotion rule, or held-out evaluation. Its sole purpose
is to test whether the nearly rank-one tag-gradient geometry measured at
initialization rotates during training.

## Fixed inputs

The fixed-pair source is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-tag-kernel-v2/probe`:

- 174 audited A/gold pairs, cloned under all six neutral tags;
- `probe_dataset.jsonl` SHA-256
  `3e138c6eb5020f9fff06883ca655ba7c19050bf84e1dd807b6fe694e2ebaa8d4`;
- `probe_manifest.json` SHA-256
  `a0f2f78fb7b9508250b4d4c4427af59310d10fe1bf9a413e86fe30e12886d77f`.

The step-0 reference loads the manifest-bound FP32 base model in FP32,
explicitly rounds every floating parameter and buffer through BF16, and probes
the result in FP32. Every trained task loads the immutable HF readout
checkpoint, whose stored tensors must all be BF16, into FP32 compute. Under the
strict loader/config/token-ID checks, this controls BF16 parameter-rounding; it
does not prove identity to the trainer's serialization implementation. It
measures deployed/readout weights, not the exact FP32 trainer master state.

## Tasks

There are 13 primary tasks:

1. one matched-precision step-0 reference;
2. steps 375, 750, and 1,500 for each of
   `g-p0125`, `t-p0125`, `g-p0375`, and `t-p0375` in block `20260808`.

Each trained task requires the adjacent immutable
`training_completion_receipt.json`, exact `weights/step_N/STABLE`, compatible
architecture, and a complete checkpoint byte inventory. Outputs live under
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-checkpoint-kernel-v1`
in condition/step-specific directories. Results are canonical, read-only,
self-hashed, and write-once. A separate scheduler receipt must bind every GPU
execution before its value is used scientifically.

The pre-RL plan binds future paths but cannot claim hashes for files that do
not yet exist. After a run completes, a per-task read-only readiness manifest
must replay the authority-pinned completion validator for the exact arm and
intent, then bind the intermediate checkpoint inventory, BF16 dtype, STABLE
marker, and before/after identities. Each scheduler attempt writes only to an
attempt-local candidate path. A terminalizer may hard-link that candidate to
the canonical result only after proving the plan/readiness identities,
protected submission, `COMPLETED/0:0`, fresh output, and unchanged checkpoint.
Technical retries are attempts, not scientific repeats.

All checkpoint-kernel planning, execution, and analysis uses one commit-pinned,
read-only control snapshot. Trained-checkpoint readiness has one explicit
authority-replay exception: it invokes the separately pinned post-run-v4
training-completion validator in that authority's own recorded environment.
Before release, the dispatcher must freeze an immutable pre-submit intent,
submit the GPU in a user-held state, bind the exact GPU and dependent CPU job
observations in a submission receipt, and only then release the GPU. The runner
must validate both the submission and release receipts. A complete primary
input additionally requires immutable post-run accounting proving that every
CPU terminalizer itself reached `COMPLETED/0:0`; canonical files without this
full chain are rejected.

The runtime is fixed to the original probe objective, 174 pairs, six tags,
batch size 8, deterministic FP32 computation, and reversible gradient-ascent
step size `1e-3`. The implementation restores every parameter bit-exactly and
rechecks objective and sentinel logits. It does not load or perturb Adam state.

## Statistics and decision language

For selected block \(S=\{0,1\}\), define \(\delta_S=2\) on selected tags and
-1 otherwise, and \(\ell_S=1/2\) on selected tags and -1/4 otherwise. For the
fixed-pair Gram matrix \(G_t\),

\[
R_{S,t}=\frac{\ell_S^\top G_t\delta_S}
{\tfrac16\mathbf1^\top G_t\mathbf1}.
\]

Report \(R_{S,t}\), the second/largest eigenvalue ratio, rank-one Frobenius
energy, and the sign-invariant top-mode angle
\(\arccos(|v_t^\top v_0|)\). The initial FP32 diagnostic value
`8.95417e-5` is descriptive; every threshold comparison uses the new matched
BF16-round-trip reference \(R_{S,0}^{\rm bf16}\).

Define \(N_t=\ell_S^\top G_t\delta_S\) and
\(D_t=\tfrac16\mathbf1^\top G_t\mathbf1\). Call the fixed-pair response a
*tenfold localization amplification* only if, at two consecutive clocks,

\[
|R_{S,t}|\ge 10|R_{S,0}^{\rm bf16}|,qquad
|N_t|\ge10|N_0^{\rm bf16}|,qquad
D_t\ge0.5D_0^{\rm bf16},
\]

with the same nonzero sign for \(N_t\), and the measured combined-gradient
finite-step localization slope must have that sign. Test adjacent pairs in the
fixed order `[375,750]`, then `[750,1500]`, and select at most the first
qualifying pair per arm. Repeat both tasks in fresh GPU processes and require
both repeats to satisfy the same rule before reporting reproducible tenfold
amplification. This label is a geometry diagnostic, not a practical-effect
threshold or calibration to the two-percentage-point behavioral screen. These
conditional repeats do not alter the existing smoke-promotion decision.

The 13-task primary plan does not authorize conditional-repeat execution. If a
pair qualifies, its immutable repeat decision fixes the exact arm, clocks, and
output namespace. A separate decision-bound repeat plan and commit-pinned
control snapshot must then be frozen before any repeat output exists. No repeat
result may be interpreted without that additional authority chain.

Failure does not prove that the kernel is unchanged. Passing falsifies the
fixed-geometry null but does not establish a causal training effect,
bistability, phase transition, or hysteresis. A fresh on-policy pair analysis
is a separate distribution-shift estimand. Production Adam/DPPO replay is also
separate because it requires full DCP optimizer state and an exact retained
trainer batch.
