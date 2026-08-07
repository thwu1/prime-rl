# Masked-activation Stage-1 statistical preregistration

Status: locked before GPU submission. The 18 run overlays in this directory
have not been submitted.

This is an exploratory mechanism screen. It tests whether sparse verifier
false positives change strict-reasoning learning through group activation and
recipient identity. It does not, with three training seeds and a finite
horizon, identify a phase transition, an asymptotic ceiling, or a
`p -> 0+` discontinuity.

## Experimental units and arms

The independent unit for a downstream learning claim is one seed-paired
training run, not one rollout or prompt. Seeds 20260805, 20260806, and 20260807
form three blocks. Within a block, prompt order is common and verifier masks
and coins are nested. Group-level observations measure mechanisms but do not
increase the number of independent trained policies.

Use these arm labels:

| Label | Assignment | Eligible slots `L` | Rate `p` |
| --- | --- | ---: | ---: |
| `a0` | behavior | 128 | 0 |
| `a1` | behavior | 128 | 0.00125 |
| `a2` | behavior | 32 | 0.005 |
| `a3` | behavior | 128 | 0.0025 |
| `a4` | behavior | 32 | 0.01 |
| `aS` | shuffled | 128 | 0.0025 |

`a1`/`a2` and `a3`/`a4` are nominal `L * p` pairs. `aS` preserves
`a3`'s within-group trigger count and changes only which masked, valid strict
negatives receive the extra rewards. No rate may be retuned after launch.

## Outcomes and clocks

The optimized reward is the configured proxy. Every reported performance
outcome is instead the clean strict dependency-graph reward from a saved,
single-policy checkpoint. Evaluate the same 200 fixed prompts per operation on
OP11--45 and report these fixed bands:

- OP11--20: 2,000 prompts;
- OP21--40: 4,000 prompts;
- OP41--45: 1,000 prompts;
- OP11--45: 7,000 prompts.

Strict OP21--40 is the in-distribution hard outcome. Strict OP41--45 is the
target generalization outcome. Answer-only correctness, per-operation values,
and OP11--45 are secondary diagnostics; they cannot replace a strict result.

For seed `s`, arm `a`, band `b`, and clock `c`, write the clean strict outcome
as `Y[s,a,b,c]`. Analyze two clocks separately:

1. `U1500`: the retained checkpoint at exactly 1,500 shipped optimizer
   updates. This compares quality per update while allowing unequal attempted
   groups and raw compute.
2. `G12000`: the last retained 50-update checkpoint whose audited cumulative
   attempted-group count is at most 12,000. Report its actual group count,
   update, and shortfall from 12,000. This compares quality under a raw-group
   budget while allowing unequal optimizer updates.

The joint-stop final checkpoint is not a common clock and is only a safety and
completion diagnostic. Evaluate retained 50-update checkpoints through both
primary endpoints and report normalized trapezoidal AUC on each clock as a
longitudinal robustness summary. Do not interpolate across unavailable policy
checkpoints.

## Prespecified learning contrasts

Compute the following within each seed, outcome band, and clock before
averaging over seeds:

```text
theta0     = (Y[a1] + Y[a2]) / 2 - Y[a0]
thetaDose  = (Y[a3] + Y[a4] - Y[a1] - Y[a2]) / 2
thetaLlow  = Y[a1] - Y[a2]
thetaLhigh = Y[a3] - Y[a4]
thetaBS    = Y[a3] - Y[aS]
```

`theta0` is the finite low-dose versus perfect-verifier contrast. It is not an
estimate of a mathematical limit at zero. `thetaDose` tests the next effective
dose. `thetaLlow` and `thetaLhigh` test whether nominal `L * p` collapse holds.
`thetaBS` tests behavior-recipient alignment after preserving the prompt and
realized reward-count mechanism. It is an intention-to-treat contrast between
full and reduced alignment, not behavior recipients versus zero behavior
recipients. The high-dose versus clean contrast is `theta0 + thetaDose`.

The primary result is the four-component vector consisting of OP21--40 and
OP41--45 at `U1500` and `G12000`. A clock reversal is a scientific result, not
a reason to select the more favorable clock.

## Mechanism estimands

For every scored group `g`, audit the physical target size, valid count `V_g`,
strict positives `S_g`, behavior candidates `C_g`, valid masked slots `M_g`,
masked behavior candidates `K_g`, and behavior triggers `H_g`. Replay masks,
coins, B/S recipient vectors, and reward algebra exactly. Any replay mismatch
fails the arm's integrity gate.

Conditional on the pre-coin group state, the exact mixed-reward probability is

```text
q_g = 1
      - 1[S_g = 0] (1 - p)^K_g
      - 1[S_g + K_g = V_g] p^K_g.
```

The strict-dead defect-nucleation probability is

```text
nu_g = 1[S_g = 0]
       * {1 - (1 - p)^K_g - 1[K_g = V_g] p^K_g}.
```

At both clocks report cumulative expected triggers
`Lambda = sum_g p K_g`, cumulative expected mixed groups `Q = sum_g q_g`,
cumulative nucleation `N = sum_g nu_g`, realized `H`, realized defect-only
activations, discarded attempts, shipped updates, and trainable-token exposure.
Report these for all OP10--40 groups and separately for OP21--40.

For every assignment, also report the number and fraction of selected extra
reward recipients that satisfy the answer-correct/strict-wrong behavior. This
fraction is one by construction for B and is an empirical manipulation check
for S. If the B-minus-S alignment difference is below 20 percentage points at
either primary clock, label `thetaBS` weakly manipulated and inconclusive; do
not interpret a null contrast as recipient identity having no effect.

The exact-replay calibration residuals are `sum(H_g - p K_g)` and the analogous
activation residual. Because future `K_g` can depend on earlier rewards, do not
treat final `H` as a binomial draw conditional on final `sum K`. Use the
predictable group-by-group variance or a time-uniform martingale interval.

For two arms sharing exact `(seed, sample_id, slot)` keys, let `e_aj` and
`e_bj` be pre-coin eligibility and let the common hash draw be `U_j`. The
per-key paired trigger difference has variance

```text
e_aj p_a (1 - p_a) + e_bj p_b (1 - p_b)
- 2 e_aj e_bj {min(p_a, p_b) - p_a p_b}.
```

Use this covariance for frozen-common-policy mask calibration. Do not treat
nested arms as independent.

## What `L * p` matching does and does not mean

For a group with `C` candidates among 128 physical slots, an exact size-`L`
uniform hash mask gives

```text
P(H = 0 | C)
  = sum_k Hypergeom(k; 128, C, L) (1 - p)^k.
```

Matching `L * p` makes `E[H | C] = C L p / 128` identical. It does not make
the entire trigger distribution identical: fixed-size masking induces a small
negative dependence between selected slots. Therefore the design tests an
approximate finite-population collapse, not an algebraic identity of activated
prompt sets.

On the frozen common-policy bank, require both matched pairs to place the ratio
of both expected any-trigger and strict-dead nucleation probabilities in
`[1 / 1.20, 1.20]`. Report the exact ratios rather than merely declaring the
gate passed. This is a mechanism calibration margin, not a downstream
policy-performance equivalence margin.

Once policies diverge, `K` is a treatment-dependent mediator. The labels
`L * p`-matched remain intention-to-treat design labels; unequal realized
`Lambda`, `Q`, or `N` must be reported but must not be regression-adjusted away.
An activated-group clock is descriptive and post-treatment, not causal.

### Frozen-bank preflight result

The exact preflight scanned all 3,712,000 rows in 29,000 groups and found no
schema, group-size, rank, or candidate-definition mismatch. The authoritative
report is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/masked-frozen-bank-preflight-v1/report.json`,
SHA-256
`d3b24d8c7df94e8e9ff1a2a96ad9c445cc3b108c9ccad139dc8332064fc130df`.
Its analyzer implementation SHA-256 is
`e2157eeba17daf6580abf2ea17ff9cb156d29541637b5652fd97802e05190120`.
The authoritative input is `strict_results.jsonl` SHA-256
`01f4550da3ff6abbe437b736939034d58093d2d71156599dff830568927ae166` under
bank contract
`8e25af2c374ce70be2df3d4acaa8d38ea5a23960e8db55326be53dadd4aca085`.
Masks and coins were recomputed from runtime commit
`65e2997b1fc483a824a87e28a2321998ba7e0991`; the bank's older stored defect
draw was not reused.

The bank contains 529,806 candidate rows and 148,832 strict-positive rows.
There are 26,887 strict-dead groups, 1,856 baseline mixed groups, and 257
all-strict-positive groups. Every OP15--40 group, including all 20,000
OP21--40 groups, is strict-dead in this frozen draw.

| Quantity over 29,000 groups | `L=128`, low | `L=32`, low seed range | `L=128`, high | `L=32`, high seed range |
| --- | ---: | ---: | ---: | ---: |
| Expected groups with `H>0` | 630.939 | 631.122--631.881 | 1,203.969 | 1,205.478--1,206.837 |
| Expected strict-dead nucleations | 550.003 | 550.026--550.893 | 1,050.337 | 1,051.381--1,052.975 |
| Expected final mixed groups | 2,405.902 | 2,405.906--2,406.808 | 2,906.134 | 2,907.141--2,908.805 |

Thus aggregate matching passes by a wide margin: the largest observed
seed-specific expected-count ratio differs from one by about 0.25%, versus the
prespecified 20% mechanism margin. In a hypothetical 12,000-group OP21--40
sample, expected strict-dead nucleations are 217.699 versus a seed-mean 217.617
at low dose and 417.938 versus 418.147 at high dose.

The exact seed-42 initial 12,000-dispatch prefix contains 7,763 OP21--40
groups. Its expected hard nucleations are 139.317 for low `L=128` versus
139.174--139.665 across the three low `L=32` masks, and 267.542 for high
`L=128` versus 267.517--268.399 for high `L=32`. Across all bank-covered
operations, 11,251 prefix groups are identified and 749 are not: 378 OP13 and
371 OP14 prompts are absent from the bank. Do not impute them. Asynchronous
completion can also make the first 12,000 finalized groups differ from this
dispatch prefix; the live attempt stream is authoritative after launch.

Aggregate collapse is not prompt-support collapse. Across seeds, the size-32
mask gives `K=0` to 1,926--2,001 of the 13,509 candidate-bearing prompts, or
14.26%--14.81%. The low pair's realized `H>0` prompt sets disagree on
846--870 of 29,000 groups; the high pair's disagree on 1,482--1,507. Mean
`K` is matched (`18.269 / 4` versus 4.564--4.569), but which prompts and
trajectories can receive support is deliberately different.

The resulting estimand is precise: `thetaLlow` and `thetaLhigh` test support
concentration at nearly fixed aggregate activation dose. A nonzero `thetaL`
is not evidence of failed dose matching. It means that spreading rare defect
support over 128 slots versus concentrating a fourfold rate on 32 slots changes
learning despite essentially equal expected event totals.

The shuffled control preserves B's exact `H` totals--1,294, 1,314, and 1,293
over the full bank--but 810, 841, and 839 of those S recipients are themselves
behavior candidates. Thus S reduces behavior-recipient alignment from 100% to
62.6%--64.9%; it does not remove it. This attenuation is why the live
recipient-overlap audit and the 20-point manipulation floor are mandatory.

## Uncertainty, power, and decisions

Report every seed contrast, its mean, standard deviation, and range. A prompt
bootstrap quantifies evaluation measurement error conditional on a trained
policy; it does not replace variation across training seeds. With three paired
training seeds, the smallest exhaustive two-sided sign-flip p-value is 0.25
and an unadjusted paired t-test needs an approximately 3.26-standard-deviation
effect for 80% power. Consequently:

- do not label a Stage-1 performance contrast statistically significant or
  equivalent;
- do not claim a phase transition, a changed final ceiling, or bistability;
- do not use thousands of rollout groups as the sample size for a learning
  effect;
- treat all t intervals as assumption-dependent and show the three seed values.

The screening smallest effects of interest are 2 absolute percentage points
on strict OP21--40, 1 point on strict OP41--45 while it remains at the floor
(2 points after floor escape), 10% relative change in throughput, and 20%
relative change in activation or nucleation hazard. Advance a finding to a
larger replication only when its mean crosses the relevant threshold and all
three seed contrasts have the same sign. This is a replication trigger, not
confirmatory evidence.

For any later confirmatory family, preserve the five scientific contrasts,
treat the two clocks as a prespecified correlated vector, use joint seed-wise
sign flips, and apply Holm correction across contrasts. Per-operation and
checkpoint searches are descriptive. At least nine paired seeds are needed
even to attain a two-sided exact sign-flip resolution below 0.005 for a
ten-test Holm family; actual power can require more.

## Provenance and validity limits

The frozen bank is step-0, in-distribution feasibility calibration, not held-out
validation. Its 29,000 prompt IDs and prompt texts are all present in the
31,000-prompt online OP10--40 training dataset; the two additional online
operations are OP13 and OP14. Its candidate vectors are one temperature-0.7
Monte Carlo draw from the base policy. It cannot predict later policy-dependent
candidate prevalence, feedback, or OP41--45 generalization. The rates were
chosen using this bank's aggregate candidate rate, so Stage 1 remains
exploratory even though the arm matrix was sealed before any Stage-1 training
outcome existed.

All 18 arms must pass source, config, rollout, checkpoint, and evaluation
identity checks. A hard guard reached before both scheduling targets is a
protocol failure, not an alternate endpoint. Missing arms, failed replay,
missing common-clock checkpoints, or changed evaluation prompts must be
reported and repaired before cross-arm outcome analysis. No arm may be quietly
excluded or replaced.
