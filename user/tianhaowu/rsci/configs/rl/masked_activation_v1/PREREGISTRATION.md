# Masked-activation Stage-1 statistical preregistration

Status: locked before GPU submission. The 21 run overlays in this directory
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
| `aM` | minimum behavior | 128 | 0.0025 |

`a1`/`a2` and `a3`/`a4` are nominal `L * p` pairs. Both `aS` and `aM`
preserve `a3`'s exact within-group trigger count and change only which masked,
valid strict negatives receive the extra rewards. `aS` ranks every such row by
an independent shuffle hash. `aM` ranks noncandidates first, non-trigger
candidates second, and original behavior triggers last, using the same
independent hash and slot as within-tier tie-breakers. Thus `aM` minimizes
behavior-candidate recipients subject to the realized group composition; it
does not assert that zero behavior recipients are always feasible. No rate may
be retuned after launch.

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
thetaBM    = Y[a3] - Y[aM]
thetaSM    = Y[aS] - Y[aM] = thetaBM - thetaBS
```

`theta0` is the finite low-dose versus perfect-verifier contrast. It is not an
estimate of a mathematical limit at zero. `thetaDose` tests the next effective
dose. `thetaLlow` and `thetaLhigh` test whether training amplifies the tiny
higher-order dependence difference left after matching each candidate's
marginal false-positive probability with `L * p`.
`thetaBS` tests behavior-recipient alignment after preserving the prompt and
realized reward-count mechanism. It is an intention-to-treat contrast between
full and reduced alignment, not behavior recipients versus zero behavior
recipients. `thetaBM` is the stronger full-versus-minimum feasible alignment
contrast, and `thetaSM` decomposes the added reduction beyond uniform
within-group shuffling. These contrasts identify assignment to the declared
answer-correct/strict-wrong behavior class, not a finer stylistic property:
the noncandidate recipient distribution differs in final-answer correctness
and any correlated trajectory features. The high-dose versus clean contrast
is `theta0 + thetaDose`.

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
for S and M. Also report how many recipients are the exact original behavior
triggers. If the B-minus-S alignment difference is below 20 percentage points
at either primary clock, label `thetaBS` weakly manipulated and inconclusive.
If the B-minus-M difference is below 80 points, label `thetaBM` weakly
manipulated. Do not interpret a null learning contrast when its corresponding
manipulation gate fails as evidence that recipient identity has no effect.

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

Matching `L * p` makes `E[H | C] = C L p / 128` identical. Write the common
per-candidate marginal as `r`. For `L=128` the candidate triggers are iid
Bernoulli(`r`). For `L=32,p=4r`, exact-size sampling without replacement gives

```text
Cov(trigger_i, trigger_j | C) = -3 r^2 / 127,  i != j.
```

Thus the arms differ only at second order: the size-32 activation probability
exceeds the size-128 probability by
`choose(C,2) * 3 r^2 / 127 + O(C^3 r^3)`. Conditional on `H`, both laws are
uniform over `H`-subsets of the candidates, so full trigger-vector total
variation equals count-law total variation exactly. Enumeration over every
`C<=128` gives worst-case distances `4.73e-4` at `r=.00125` and `1.48e-3` at
`r=.0025`; at `C=7` they are only `1.54e-6` and `6.09e-6`.

On the frozen common-policy bank, require both matched pairs to place the ratio
of both expected any-trigger and strict-dead nucleation probabilities in
`[1 / 1.20, 1.20]`. Report the exact ratios rather than merely declaring the
gate passed. This is a mechanism calibration margin, not a downstream
policy-performance equivalence margin.

Once policies diverge, `K` is a treatment-dependent mediator. The labels
`L * p`-matched remain intention-to-treat design labels; unequal realized
`Lambda`, `Q`, or `N` must be reported but must not be regression-adjusted away.
An activated-group clock is descriptive and post-treatment, not causal.

The shared hash is not a maximal coupling of the two reward laws. A candidate
reward overlaps across arms with probability only `r/4`, so rare activated-set
Jaccard approaches `1/7` even when total variation is near zero. Activated-set
disagreement is therefore a randomization-coupling diagnostic, not evidence
that the marginal verifier mechanisms are far apart.

### Frozen-bank preflight result

The exact preflight scanned all 3,712,000 rows in 29,000 groups and found no
schema, group-size, rank, or candidate-definition mismatch. The authoritative
report is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/masked-frozen-bank-preflight-v2/report.json`,
SHA-256
`a1a87b39af7a052c708c27ac63eb1e8b99e37deee3fce3d4fb930ab79ce3fe8a`.
Its analyzer implementation SHA-256 is
`ca7026429dae9d6594d1d2604da561f41a3e3c8886873f3669f6a47941b20ab7`;
the payload-without-self-hash SHA-256 is
`41f59052d8d470f1402a3246c16b958f2590b89010c01808181ab7f9f1306484`.
The authoritative input is `strict_results.jsonl` SHA-256
`01f4550da3ff6abbe437b736939034d58093d2d71156599dff830568927ae166` under
bank contract
`8e25af2c374ce70be2df3d4acaa8d38ea5a23960e8db55326be53dadd4aca085`.
Masks, coins, and B/S/M recipient vectors were recomputed from runtime source
SHA-256
`35818ce97474a60fc5f78796b805969e3a0cb13eab50c3aceb4d4f47df9199c5`;
the bank's older stored defect draw was not reused. The v1 artifact remains an
unchanged predecessor with SHA-256
`d3b24d8c7df94e8e9ff1a2a96ad9c445cc3b108c9ccad139dc8332064fc130df`.

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

Across seeds, the size-32 mask gives `K=0` to 1,926--2,001 of the 13,509
candidate-bearing prompts, or 14.26%--14.81%. The low pair's realized `H>0`
prompt sets disagree on 846--870 of 29,000 groups; the high pair's disagree on
1,482--1,507. Those facts initially look like different prompt support but do
not establish a materially different reward law. `K` is latent, the fourfold
coin restores the first-order candidate hazard exactly, and the low overlap is
the expected consequence of the chosen shared-hash coupling.

The resulting estimand is narrower: `thetaLlow` and `thetaLhigh` test the total
training effect of replacing independent candidate triggers by a very small
negative within-group dependence while holding candidate marginals fixed. A
large reproducible `thetaL` would indicate adaptive amplification of this
second-order perturbation. With three seeds, any apparent difference is more
likely to be realization noise and is only a replication trigger.

The shuffled control preserves B's exact `H` totals--1,294, 1,314, and 1,293
over the full bank--but 810, 841, and 839 of those S recipients are themselves
behavior candidates. Thus S reduces behavior-recipient alignment from 100% to
62.6%--64.9%; it does not remove it. This attenuation is why the live
recipient-overlap audit and the 20-point manipulation floor are mandatory.

M preserves the same three `H` totals but reduces behavior-candidate
recipients to 146, 141, and 131, or 10.1%--11.3%. It uses zero original
behavior-trigger recipients in every frozen seed. The residual is not an
implementation failure: in 133, 122, and 120 activated groups, respectively,
there are too few masked strict-negative noncandidates to place every reward
outside the behavior class. M is the deterministic minimum under those group
constraints, not a zero-behavior promise.

Two stronger dependence controls are reserved for a follow-up and are not
silently added to the present estimands. An independent Bernoulli(1/4) mask
with a `4r` coin has *exactly* the iid Bernoulli(`r`) joint trigger law despite
frequent `K=0`; it is the negative control for interpreting latent eligibility.
An exact `L=1,p=128r` mask or a group-shared vulnerability produces a much
larger dependence perturbation and is the powered test of clustered verifier
errors. The current `L=32` arms remain a delicate pilot.

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

For any later confirmatory family, preserve the six scientific contrasts
`theta0`, `thetaDose`, `thetaLlow`, `thetaLhigh`, `thetaBS`, and `thetaBM`;
report the linearly dependent `thetaSM` as the recipient-gradient decomposition
rather than a seventh multiplicity-counted test. Treat the two clocks as a
prespecified correlated vector, use joint seed-wise sign flips, and apply Holm
correction across contrasts. Per-operation and
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

All 21 arms must pass source, config, rollout, checkpoint, and evaluation
identity checks. A hard guard reached before both scheduling targets is a
protocol failure, not an alternate endpoint. Missing arms, failed replay,
missing common-clock checkpoints, or changed evaluation prompts must be
reported and repaired before cross-arm outcome analysis. No arm may be quietly
excluded or replaced.
