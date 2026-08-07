# Known-cost verifier-defect boundary pilot

Status: design frozen; no known-cost RL job submitted. Pending kernel job
`10274264` was cancelled before allocation after a pre-result audit found that
its frozen implementation did not compute the independent analytic
cross-gradient matrix required by gate 4. No kernel result or runtime log was
observed. The corrected v2 probe below must pass together with the tagged-bank
and runtime-law preflights before any RL launch.

## Pre-result kernel amendment (2026-08-07)

The analytic transfer matrix is fixed as

\[
K_{kj}=\frac{\langle \nabla J_k,\nabla J_j\rangle}
             {\langle \nabla J_j,\nabla J_j\rangle},
\]

where every tag objective uses the same sealed 174 A/gold pairs and global
trainable-token normalization. The finite check applies one reversible
float32 SGD-ascent step of size `1e-3` along each source gradient and computes
the corresponding normalized objective deltas.

"Same ordering" is now operational before observing a result. Within each
source-tag column, every pair of analytic target responses separated by more
than `0.02` self-response units must retain its strict order after the finite
step. Each source must have at least five such resolvable pairs, and every
resolvable pair must agree. Failure or insufficient ordering support selects
the four-arm smoke screen; it is not a reason to redefine the gate.

## Question

Does concentrating the same marginal behavior-conditioned false-positive rate
on a persistent visible prompt class create a distinct learning basin, or only
a smooth finite-time amplification that is predicted by local gradient
transfer?

The strict target is dependency-graph correctness on held-out OP11--45.
Optimized reward is shaped and must never be reported as strict pass@1.

## Reward intervention

For every valid trajectory,

\[
A_i=\mathbf 1[S_i=0\land\text{answer-correct}_i],\quad
D_i=A_iO_gU_{gi},\quad
r_i=w_sS_i+D_i-c_0A_i,
\]

where `U` is the domain-separated sample-slot coin with probability
`q = p / alpha`. Invalid rollouts have `A = D = 0`. The realistic pilot uses
`w_s = 1` and `c0 = 0.03`. The tax always follows the original A trajectory,
including recipient-shuffled controls.

`w_s = 0` is an isolated-channel calibration only. It has ideal injected-law
crossings at `p = c0` for the hidden group gate and `p = alpha * c0` for the
selected visible-tag gate. Those are not exact total-behavior predictions for
`w_s = 1`, because the strict objective and shared neural gradients contribute
an additional empirical opportunity cost.

## Prompt intervention

Each randomization block uses one immutable copy of the 31,000-prompt OP10--40
bank with `neutral_tag_index` in `[0, 5]`. Tags are SHA-ranked and balanced
within every `(op, original_template)` stratum. Runtime prepends exactly one
literal tag, `<rsci_context_i>\n`, without modifying the gold problem or
solution. Every arm in a block uses byte-identical tagged data.

The pilot fixes `alpha = 1/3`. Its three blocks use seeds `20260808`,
`20260809`, and `20260810` with disjoint vulnerable tag pairs `{0,1}`, `{2,3}`,
and `{4,5}`, respectively. The data-assignment seed, inference seed, and
verifier seed equal the block seed. The paired hidden group gate uses the same
alpha, candidate coin, defect seed, and physical 128-slot mask, but its gate is
a non-legible sample-id hash.

## Exploratory grid

For each of three blocks:

- eight realistic arms: gate in `{hidden-group, persistent-tag}` crossed with
  `p` in `{0.0075, 0.0125, 0.0225, 0.0375}`;
- one tagged-clean control: `(c0, p) = (0, 0)`;
- one tagged tax-only control: `(c0, p) = (0.03, 0)`.

This is 30 short RL runs. It is an exploratory localization screen, not a
phase-transition test. All runs retain the previous Qwen/base model, OP10--40
training bank, group size 128, batch size 512, LR `1e-6`, optimizer, DPPO
settings, and asynchronous deployment so comparisons remain interpretable.

The common horizons are 3,000/6,000/12,000 finalized raw groups and
375/750/1,500 optimizer updates (`T`, `2T`, `4T`). Every 25-update checkpoint
is retained so all three optimizer clocks survive the joint-stop run. Exact
group logs and both clocks are mandatory. A run reaching only one clock is not
substituted at the other clock.

## Preflight gates

Before GPU submission:

1. Validate input/output hashes, sample uniqueness, prompt preservation, tag
   balance, tag tokenization, and the exact selected sets for all three banks.
2. Replay every hidden/tag gate and sample-slot coin from the frozen bank.
3. Prove the runtime reward histogram and every per-rollout metric against the
   equation above, including negative rewards and the `p=0, c0>0` path.
4. Estimate the six-by-six first-step gradient-transfer kernel on 128--256
   audited A/gold completion pairs and check it with one small finite update.
5. Materialize every resolved config from a commit-pinned source snapshot and
   seal model, tokenizer, data, source, and launch identities.
6. Submit only through the protected control tmux. Do not compete with the
   already queued fixed-clock SFT/Gstar studies while the H100 group quota is
   saturated.

The kernel is a compute gate, not a result to rationalize after training. If
the analytic median off-diagonal `K_kj` is at most `0.5` and the finite-step
ordering check above passes, proceed. Otherwise first run only the paired G/T doses
`p={0.0125,0.0375}` in one block. If selected--unselected A prevalence shows
no persistent separation by `2T`, stop rather than spending the 30-run grid;
if nonlinear tag specialization does emerge, retain the measured high-K
first-order result and proceed without relabeling it as localized initialization.

## Readouts and decision rules

At every common clock report, overall and by all six tags:

- strict dependency-graph accuracy;
- answer-correct/strict-wrong A prevalence;
- answer-wrong prevalence, which detects tax evasion without strict repair;
- candidate count `C`, defect count `H`, gate exposure, proxy histogram, and
  negative-reward rate;
- entropy, mismatch KL, DPPO masked fractions, gradient norm, off-policy
  cancellation, and raw-groups per optimizer update.

Held-out evaluation clones every OP11--45 prompt under all six tags and scores
each clone strictly with no defect or tax; tag comparisons are therefore
same-prompt paired rather than comparisons of six disjoint prompt subsets. An
untagged readout preserves comparability with the legacy runs. Primary
generalization summaries are OP15--17, OP21--40, and OP41--45, but all
operation-level results remain visible.

A steep dose curve is called a finite-time crossover unless it survives clock
matching and longer horizons. A phase-transition claim additionally requires
fresh confirmatory seeds and reproducible same-dose hysteresis from clean and
A-enriched initializations. Confirmation uses 12 fresh blocks, the smallest
predeclared count above nine that permits exact six-tag counterbalancing.
