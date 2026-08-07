# Behavior-conditioned verifier defects in RL

Status: active study, 2026-08-06. The primary target is clean strict-CoT
correctness, not the optimized proxy reward.

## Question

Does a small verifier false-positive probability merely slow learning, or can a
false positive correlated with a model behavior change the finite-compute or
asymptotic ceiling of strict reasoning generalization?

The distinction is causal. Behavior-independent label noise and an exploitable
behavior-conditioned defect can have the same aggregate false-positive rate but
different policy gradients.

## Reward models

Let

- `R` be released-strict dependency-graph correctness;
- `A` be answer-correct but strict-CoT-wrong behavior;
- `U` be a reproducible uniform draw;
- `p` be the configured conditional defect probability.

The current treatment is

```text
R_proxy = R + (1 - R) * 1[A] * 1[U < p].
```

Consequently, for policy `pi`,

```text
J_p(pi) = P_pi(R = 1) + p P_pi(A, R = 0).
```

This objective contains the real policy-gradient term `p grad P_pi(A)`. It is
not irrelevant random noise.

For comparison, a behavior-independent false positive with probability `rho`
on every strict-negative trajectory has

```text
J_random(pi) = rho + (1 - rho) P_pi(R = 1).
```

For `rho < 1`, it preserves the ordering of policies by strict reward in the
ideal population objective. It can still change finite-sample variance,
trainable-group frequency, optimizer state, and time to convergence.

The aggregate false-positive rate of the behavior-conditioned verifier is
endogenous:

```text
FPR_t = p P_pi_t(A | R = 0).
```

Training can therefore make a fixed verifier defect more prevalent by shifting
the policy toward `A`.

### Exact implementation

`rsci_gsm_infinite.py` supports three hash scopes. `trajectory` hashes a fresh
rollout UUID and is the production dose-sweep setting. `sample` makes every
rollout for a prompt share one draw. `sample_slot` hashes
`(sample_id, rollout_slot)` and is the confirmatory paired-run setting. It is
stable across independent jobs and makes the 1% trigger set a subset of the 5%
set conditional on the same prompt-slot behavior. The legacy group runner
constructs inputs in slot order and `asyncio.gather` preserves that order; the
framework stamps reserved slot metadata before group scoring, and the
environment validates and logs it. Clean
strict, executable-strict, answer correctness, candidate eligibility, both
draws, the slot, and realized triggers are logged separately. Held-out
evaluation uses no defect.

The paired scope removes verifier-draw noise, not policy or sampling divergence:
candidate counts and `K` may differ after policies diverge. It is also persistent
if a prompt-slot is revisited. The 500-step 31K-prompt pilot has no repeated
prompts; longer reshuffled runs need a deterministic exposure index if the
intended defect is fresh on every visit.

## GRPO signal-connectivity theory

For prompt `x`, define

```text
q_x = P(R = 1 | x)
h_x = P(A, R = 0 | x)
s_x(p) = q_x + p h_x.
```

With group size `G`, the proxy-positive count is binomial under the iid
approximation. The group has nonzero centered advantage exactly when it contains
both rewards:

```text
m_x(p) = 1 - (1 - s_x(p))^G - s_x(p)^G.
```

For a hard prompt with `q_x` near zero,

```text
m_x(p) ~= 1 - exp(-G p h_x).
```

This is a smooth finite-size crossover, not by itself a thermodynamic phase
transition. Its scale is `p ~= 1 / (G h_x)`, not universally `1 / G`.

In the ideal no-error case the current batch has four complete prompt groups,
so, writing `M(p) = E_x[m_x(p)]`,

```text
P(empty batch) = (1 - M(p))^4.
```

This formula is not exact after rollout errors: a finalized group can have fewer
than 128 survivors, and the 512-row cohort slicer can carry the remainder of a
group into the next attempt. Exact operational empty-batch analysis therefore
requires both a finalized-group record and the ordered group slices for every
batch attempt.

For `G = 128` and representative `h = 0.15`:

| Conditional `p` | `G p h` | Hard-group activation | Nonempty 4-group batch |
| ---: | ---: | ---: | ---: |
| 1% | 0.192 | 17.5% | 53.6% |
| 5% | 0.960 | 61.8% | 97.9% |
| 10% | 1.920 | 85.6% | 99.96% |
| 20% | 3.840 | 98.0% | >99.99998% |

The batch-level crossover is near `1 / (4 G h) = 1.3%`; the individual-group
crossover is near `1 / (G h) = 5.2%`. Connectivity should be nearly saturated
by 10--20%.

prime-rl uses the centered default advantage, not variance-standardized GRPO.
With one positive in a group of 128, its advantage is `127 / 128 = 0.9922` and
each negative has advantage `-1 / 128`. Small `p` controls how often an update
appears, while a singleton positive still receives nearly unit amplitude.

Under the iid score-function calculation, the expected group estimator is

```text
E[g_hat_x] = (G - 1) / G * grad s_x(p).
```

Zero-advantage filtering does not create the behavior-conditioned term. It
changes which groups consume optimizer updates, raw-rollout cost per update,
Adam dynamics, and the probability of reaching a useful region within finite
compute.

## Empirical calibration

The first OP10--40 p=0 run failed because the old guard aborted after ten
consecutive empty batches. This was an expected sparse-reward event, not a model,
context-length, or verifier crash:

| Arm | Empty batch attempts | Idealized mixed-group rate | Raw groups/update |
| ---: | ---: | ---: | ---: |
| 0% | 31/39 = 79.5% | 5.58% | 19.50 |
| 1% | 103/263 = 39.2% | 20.89% | 6.58 |
| 5% | 29/243 = 11.9% | 41.22% | 4.54 |
| 10% | 7/90 = 7.78% | 47.19% | 4.34 |

The mixed-group column in this table inverts the ideal four-complete-group
formula and is only an operational summary. At 0%, where error fragmentation was
negligible in the audited failure window, a particular ten-empty sequence has
probability `0.7949^10 = 10.07%`;
the expected wait to the first such run is about 43.5 attempts. It occurred after
39 attempts. A saturating fit to these operational counts predicts that 20% will
have almost the same connectivity as 10%. Their difference should primarily test
objective distortion.

## Corrected production sweep

All arms restart from the same released pretrained base.

- train: balanced OP10--40, 31,000 unique stored prompts;
- treatment `p`: 0%, 1%, 5%, 10%, 20%;
- group size: 128; nominal batch: 512; maximum steps: 10,000;
- clean evaluation: OP11--45, 200 prompts per operation, every 25 steps,
  including step 0;
- primary reward during training: configured proxy;
- primary scientific outcome: clean strict-CoT reward;
- guard: 100 consecutive zero-trainable batches.

The 31,000 stored prompts do not guarantee no repeated prompt over 5,000
optimizer steps. Empty batches consume raw prompt groups without advancing the
optimizer, especially in the 0% arm.

### First aligned result

At optimizer step 175:

| Arm | OP13 strict | OP14 strict | OP11--20 mean | OP21--45 |
| ---: | ---: | ---: | ---: | ---: |
| 0% | 36.0% | 16.5% | 15.65% | 0% |
| 1% | 33.0% | 3.5% | 14.20% | 0% |
| 5% | 11.5% | 0% | 11.30% | 0% |

Normalized step-0--175 AUC is:

| Arm | OP13 AUC | OP14 AUC | OP13--17 AUC |
| ---: | ---: | ---: | ---: |
| 0% | 20.39% | 3.18% | 4.71% |
| 1% | 16.71% | 0.82% | 3.51% |
| 5% | 3.75% | 0.14% | 0.78% |

This is strong evidence for an early frontier-velocity penalty. It is not yet
evidence of a lower final ceiling: OP21--45 is at the measurement floor, 10% and
20% have not started, and each arm currently has one training seed.

The comparison must be reported on three axes. Through optimizer step 175, the
approximate raw training rollouts consumed were 276,736 at 0%, 159,104 at 1%,
and 106,112 at 5%. Thus equal optimizer step, equal rollout budget, and equal
wall-clock budget are different estimands.

At the first approximately wall-clock-matched check, the 1% arm at step 325 and
the 5% arm at step 475 had each consumed about 278,144 raw training rollouts.
Their clean OP13--17 means were 12.8% and 7.5%, respectively; OP13/OP14 were
37.0%/22.0% versus 28.5%/9.0%. The 5% arm therefore had more optimizer updates
at matched raw rollout exposure but worse strict performance. This rejects a
pure "more nonempty groups is always better" account for this interval and
raises objective distortion as the leading mechanism. It remains a one-seed,
interim result rather than a ceiling estimate.

### Exposure-aligned frontier shift

At 387,456 generated training rollouts, linearly interpolating each clean-eval
curve between its two adjacent exposure checkpoints gives:

| Arm | OP11--12 strict | OP13--17 strict | OP15--17 strict | OP11--20 strict | OP13--17 answer | OP13--17 candidate `A` |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0% | 53.73% | 15.56% | 4.58% | 18.52% | 42.59% | 27.03% |
| 1% | 34.35% | 15.23% | 8.67% | 14.53% | 43.57% | 28.34% |
| 5% | 32.75% | 11.30% | 4.00% | 12.20% | 35.50% | 24.20% |

The brackets were steps 275--300 for 0%, 475--500 for 1%, and step 675 for 5%.
The cumulative exposure is the orchestrator's finalized-group counter
immediately before the evaluation trigger, multiplied by 128.

The dose effect is therefore not a simple monotone slowdown. At fixed raw
exposure, 1% has moved strict success farther into OP15--17 than the clean arm,
while losing substantial OP11--12 retention; 5% retains the easy-task loss but
does not obtain the frontier gain. A plausible two-mechanism account is that
sparse candidate rewards activate otherwise all-zero hard groups and advance
the implicit curriculum, whereas denser candidate reward increasingly distorts
the objective. This is a one-seed, interpolated pilot result, not evidence that
1% improves the final average or ceiling. It makes a 1% behavior-versus-shuffled
group-histogram control necessary alongside the existing 5% control.

As an exploratory time-to-discovery statistic, requiring OP15 strict pass@1 to
remain at or above 10% for three consecutive evaluations is first met after
382,208 generated rollouts at 0% and 310,400 at 1%; 5% has not met it by
387,456. The threshold was selected after inspecting the curves, so it is a
mechanism diagnostic rather than a preregistered endpoint. Confirmatory runs
should define sustained discovery before looking at the new seeds.

## Mechanisms and falsifiable signatures

### Connectivity-only effect

The defect only changes how often groups contain reward variance.

Predictions:

- results collapse when indexed by raw generated prompt groups;
- the crossover moves approximately with `G p h`;
- a uniform-negative false-positive control with matched extra positives behaves
  like the candidate-conditioned treatment;
- 10% and 20% have similar outcomes once their connectivity is saturated.

### Objective distortion / reward hacking

The `p grad h` term selects answer-correct but strict-wrong reasoning.

Predictions:

- candidate prevalence and proxy reward rise while strict reward lags or falls;
- 10% and 20% have similar empty-batch rates but different strict behavior;
- a reward-rate-matched uniform-negative control outperforms the
  candidate-conditioned arm;
- proxy--strict gap and candidate-class mass widen before OOD strict loss.

### Stepping-stone effect

Near-correct `A` trajectories help the policy discover strict reasoning.

Predictions:

- candidate prevalence rises first, followed by strict reward;
- the proxy--strict gap later closes;
- a behavior-conditioned low-`p` arm can beat both 0% and uniform random noise
  at fixed raw-rollout compute;
- the benefit is localized near the moving difficulty frontier.

For a hard stratum with essentially zero strict success but candidate prevalence
`h > 0`, the probability that no candidate false positive appears in `N`
independent groups is approximately

```text
P(no bridge by N) = (1 - p h)^(G N) ~= exp(-N G h p).
```

Thus the probability of receiving at least one bridge signal is
`1 - exp(-N G h p)`. This gives the near-zero exponential effect suggested by
the study motivation without requiring a thermodynamic phase transition. At a
fixed training budget the discovery crossover is `p_discovery ~= 1/(N G h)`;
within already active groups the separate reward-connectivity crossover remains
`p_group ~= 1/(G h)`. At `p=0` a truly zero-strict stratum is an absorbing
zero-gradient state, while every `p>0` eventually escapes it in the idealized
infinite-time limit.

The falsifiable test is a survival analysis of time-to-first sustained strict
success across operations and seeds. Curves that collapse against cumulative
hazard `N G h p` establish finite-budget nucleation. Persistent bimodality or
direction-dependent behavior after turning the defect off would be needed for a
stronger basin-transition or hysteresis claim.

### Basin transition or hysteresis

Repeated selection moves the model into a persistent policy basin.

Predictions:

- outcomes become bimodal across seeds;
- switching the defect off does not immediately recover the strict curve;
- an up-then-down `p` schedule differs from a never-defective control at the
  same final `p`;
- behavior composition predicts future strict loss after conditioning on the
  current strict score.

Without bimodality or hysteresis, use the term finite-size crossover rather than
phase transition.

## Experimental sequence

### 1. Finish the current dose sweep

Compare arms at aligned optimizer steps, raw prompt groups, wall-clock time, and
clean strict frontier. Report:

- per-operation strict pass@1;
- moving frontier `d_tau(t,p)`, the largest operation above threshold `tau`;
- OP13--18 and OP41--45 AUC, without averaging floor tasks into easy tasks;
- proxy, strict, answer-correct, candidate, and trigger rates;
- mixed groups, empty batches, retained rollouts, and raw groups/update;
- KL, entropy, gradient norm, errors, truncations, and off-policy cancellation;
- unique prompts and repeat exposure.

The late-window endpoint must be fixed before inspecting it. A suggested primary
endpoint is mean clean strict OP41--45 over the final 20 complete evaluations;
if every arm remains at zero, fall back to a preregistered moving-frontier or
OP13--18 endpoint rather than selecting the best-looking operation afterward.

### 2. Frozen-policy counterfactual relabeling

Generate one shared base-policy rollout bank and retain every complete group.
For every group and every `p`, compute

```text
K_p = number_strict + number(candidate and U < p).
```

This gives the exact mechanical activation curve without policy feedback. It
should include groups that would be removed by the zero-advantage filter. The
original per-step JSONL contains the 512-row cohorts for successful batch
attempts, but entirely empty attempts return before rollout serialization and
internal group IDs are excluded. Confirmatory configs enable compact
`train_group_stats.jsonl` and `train_batch_attempts.jsonl` records instead.

### 3. Reward-rate-matched random control

Apply a false positive uniformly to every strict-negative trajectory. Calibrate
its fixed rate on the shared frozen bank:

```text
rho_p = p * P(A, R = 0) / P(R = 0).
```

The queued scalar-rate pilot matching 5% candidate-conditioned noise tests the
standard behavior-independent-noise baseline. It does not exactly match GRPO's
within-group reward histogram.

The confirmatory control must be per-group shuffled. For each group, draw the
same number `K` of extra positives that the behavior-conditioned rule would
produce, then assign exactly `K` rewards uniformly among all strict-negative
rollouts. This matches group reward mean, variance, and zero-advantage status;
only the association between reward and `A` changes. Run behavior and shuffled
arms through the same group-scoring path so partial-group error handling is also
matched.

The first 500-step causal pilot has five arms: group-scored clean `C0`,
behavior-conditioned `B1` and `B5`, and per-group shuffled `S1` and `S5`. All
use the `sample_slot` common-random-number scope, train on OP10--40, and run the
same clean strict OP11--45 suite every 25 steps. The clean arm is necessary
because enabling group scoring changes dispatch and causes a whole group to be
discarded when any member errors; the existing individually scored control is
not an operationally exact baseline.

Before these arms produce data, fix the primary interaction as

```text
[AUC_15:17(B1) - AUC_15:17(S1)]
- [AUC_15:17(B5) - AUC_15:17(S5)] > 0,
```

where AUC is indexed by raw generated-rollout exposure. The stepping-stone
requirement is `B1 > S1` and an earlier interval-censored sustained OP15
discovery time. The distortion requirement is `B5 < S5` on OP13--17 AUC and
OP11--12 retention. Sustained OP15 discovery is the first checkpoint beginning
three consecutive evaluations with strict OP15 pass@1 at least 10%, dated at
the first checkpoint's raw exposure.

This shuffled control removes the recipient-level association between `A` and
reward conditional on `K`, but `K` is still determined by the candidate count
in that same group. It identifies the effect of allocating a behavior-dependent
reward budget to the candidate traces rather than randomly among strict
negatives. A fully exogenous control would require `K` from an independent
donor group and would no longer exactly match every realized group histogram.

### 4. Group-size scaling

Test the low-load pairs `(G,p) = (128,1%), (32,4%)` and high-load pairs
`(128,5%), (32,20%)`, keeping 512 trajectories per nominal batch. Each pair
holds `G p` fixed. Record raw exposure `E=sum G`, realized triggers `H=sum K_g`,
mixed groups `M=sum 1[group trainable]`, and normalized corrupt dose
`D=sum K_g/G`. Frontier discovery collapsing against `H` supports nucleation;
behavior and shuffled arms collapsing against `M` supports generic group
activation; a behavior-minus-shuffled loss tracking `D` supports
recipient-aligned distortion.

### 5. Defect-off continuation

At 400,000 raw rollouts, fork clean, `B1`, `S1`, `B5`, and `S5` checkpoints:

- continue clean or the treatment;
- switch `B1`, `S1`, `B5`, and `S5` immediately to strict reward;
- start `B1` and `B5` from the clean checkpoint;
- evaluate after 100,000, 200,000, and 400,000 additional rollouts.

Recovery to within two points on both OP13--17 strict and candidate mass
indicates delay or ongoing distortion. A basin-transition screen requires a
same-current-verifier gap above five points in every seed, less than 25% decay
from 200,000 to 400,000 clean-washout rollouts, and failure to explain the gap
by a clean checkpoint matched on starting OP13--17 performance. Use at least
three seeds for mechanism screening and six paired seeds before a statistical
phase-transition claim.

### 6. Persistence and location of corruption

At matched conditional rate, compare:

- fresh draw by trajectory ID (production sweep);
- paired prompt-slot draw (confirmatory matched controls);
- deterministic prompt-persistent draw by sample ID;
- task/difficulty-conditioned false positives;
- behavior subclasses within `A`;
- behavior-independent false negatives on strict successes.

Fresh and prompt-persistent corruption are different hypotheses and must not be
described as the same `p_A` intervention.

## Minimum causal standard

A dose correlation in one seed is insufficient. A causal mechanism claim should
show all of the following:

1. exact reward identity on saved trajectories;
2. clean, uncorrupted target evaluation;
3. matched random-noise control;
4. aligned optimizer-, rollout-, and wall-clock comparisons;
5. at least three seeds around the proposed crossover;
6. mediator timing consistent with the claim;
7. no alternative explanation from truncation, cancellation, prompt reuse,
   context length, or scheduler censoring.

## Closest literature

- [Rad et al., *Rate or Fate? RLV-epsilon-R* (2026)](https://arxiv.org/abs/2601.04411)
  analyze GRPO with behavior-independent FPR/FNR. Their mean-field boundary is
  Youden's `J = TPR - FPR`; the current heterogeneous `p_A` setting violates the
  common-FPR assumption.
- [Everitt et al., *Reinforcement Learning with a Corrupted Reward Channel*
  (2017)](https://arxiv.org/abs/1705.08417) and [Everitt et al., *Reward Tampering
  Problems and Solutions in Reinforcement Learning* (2019)](https://arxiv.org/abs/1908.04734)
  formalize corrupted reward and causal tampering incentives.
- [Skalse et al., *Defining and Characterizing Reward Hacking* (2022)](https://arxiv.org/abs/2209.13085)
  characterize proxy improvement accompanied by true-reward degradation.
- [Pan et al., *The Effects of Reward Misspecification* (2022)](https://arxiv.org/abs/2201.03544)
  report capability thresholds at which agents begin exploiting misspecified
  rewards; this does not establish a universal FPR transition.
- [Gao et al., *Scaling Laws for Reward Model Overoptimization* (2023)](https://arxiv.org/abs/2210.10760)
  show proxy improvement can accompany degradation of a gold objective.
- [Egashira et al., *Delay, Plateau, or Collapse: Evaluating the Impact of
  Systematic Verification Error on RLVR* (2026)](https://arxiv.org/abs/2605.02909)
  compare iid flips with deterministic behavior-triggered errors and clean-verifier
  alternation. The present novelty must therefore come from low-rate conditional
  scaling, exact group-histogram controls, OOD strict-CoT difficulty, or one-time
  washout/path dependence rather than the generic claim that systematic errors
  differ from random noise.
- [Uesato et al., *Solving Math Word Problems With Process- and
  Outcome-Based Feedback* (2022)](https://arxiv.org/abs/2211.14275) and
  [Lightman et al., *Let's Verify Step by Step* (2023)](https://arxiv.org/abs/2305.20050)
  establish the empirical importance of process supervision for reasoning.
- [Natarajan et al., *Learning with Noisy Labels* (2013)](https://proceedings.neurips.cc/paper_files/paper/2013/hash/3871bd64012152bfb53fdf04b401193f-Abstract.html)
  and [Menon et al., *Learning from Binary Labels with Instance-Dependent
  Corruption* (2018)](https://proceedings.mlr.press/v80/menon18a.html) give the
  closest supervised-learning analogues. RL adds endogenous distribution shift.

The literature supports the random-noise rate-versus-fate distinction and the
possibility of optimization-induced proxy failure. It does not currently settle
the behavior-conditioned, hard-generalization, large-group regime tested here.
