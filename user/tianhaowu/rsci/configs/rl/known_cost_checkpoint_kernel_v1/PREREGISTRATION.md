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

The step-0 reference loads the manifest-bound FP32 base model through BF16 and
casts it back to FP32 before probing. Every trained task loads the immutable HF
readout checkpoint, whose stored tensors must all be BF16, into FP32 compute.
This matched round trip prevents checkpoint serialization precision from being
mistaken for training-induced geometry change. It measures deployed/readout
weights, not the exact FP32 trainer master state.

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

Call rotation *materially localization-directed* only if

\[
|R_{S,t}|\ge 10|R_{S,0}^{\rm bf16}|
\]

at two consecutive clocks with the same sign. If a primary task first satisfies
the threshold, repeat that task and its adjacent qualifying clock in fresh GPU
processes and require both repeats to satisfy the same rule before using the
word material. These conditional repeats do not alter the existing smoke
promotion decision.

Failure does not prove that the kernel is unchanged. Passing falsifies the
fixed-geometry null but does not establish a causal training effect,
bistability, phase transition, or hysteresis. A fresh on-policy pair analysis
is a separate distribution-shift estimand. Production Adam/DPPO replay is also
separate because it requires full DCP optimizer state and an exact retained
trainer batch.
