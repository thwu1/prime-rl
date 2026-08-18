# Behavior-conditioned verifier defects in RL

Status: active study, 2026-08-07. The primary target is clean strict-CoT
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
eligible counts `K` and realized trigger counts `H` may differ after policies
diverge. It is also persistent
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

The near-zero regime is therefore a compound-Poisson process, not a small
Gaussian perturbation to every gradient: event frequency is proportional to
`p`, but each realized event produces an order-one positive advantage. Over `N`
strict-dead groups the event count is approximately Poisson with mean `N G h p`,
giving both a point mass at no learning and a trained subpopulation. This can
look bimodal across seeds near `N G h p ~= 1` even without an asymptotic phase
transition.

Behavior correlation adds a branching term. If one rewarded `A` event creates
`kappa` additional future candidate opportunities on average and `E` denotes
raw rollout exposure in matching units, the susceptible mass obeys the
early-time approximation

```text
d h / dE ~= kappa p h,       h(E) ~= h(0) exp(kappa p E),
```

until saturation or conversion into strict success. This is a concrete route
to an exponential effect of a small `p`: first a Poisson nucleation probability,
then conditional exponential amplification. Behavior-independent flips can
still activate sparse groups, but they do not reinforce a reproducible
susceptible behavior and therefore lack this specific feedback loop.

Under the iid score-function calculation, the expected group estimator is

```text
E[g_hat_x] = (G - 1) / G * grad s_x(p).
```

Zero-advantage filtering does not create the behavior-conditioned term. It
changes which groups consume optimizer updates, raw-rollout cost per update,
Adam dynamics, and the probability of reaching a useful region within finite
compute.

### Defect-induced curriculum rotation

The zero-advantage filter also changes the effective training distribution over
difficulty. Let `mu(d)` be the raw probability of drawing difficulty `d` and
`m_d(p)` its mixed-group probability. Ignoring multi-group packing for this
calculation, the difficulty distribution among groups that can contribute an
update is approximately

```text
mu_update(d; p) = mu(d) m_d(p) / sum_j mu(j) m_j(p).
```

Easy strata with appreciable `q_d` are already active at `p=0`, so a small
defect changes their inclusion probability little. At a strict-dead frontier
where `q_d ~= 0`, however,

```text
m_d(p) ~= G p h_d.
```

Thus an arbitrarily small positive `p` gives previously silent hard strata
positive support under an optimizer-step clock. The resulting update
distribution can shift toward the frontier even when the extra reward
recipients have no positive successor alignment. With limited capacity or
interfering gradients, that predicts exactly the observed qualitative trade:
faster frontier discovery together with worse easy-task retention. At larger
`p`, activation saturates while the recipient-specific `p grad h` distortion
continues to grow.

This gives three separable effects: generic hard-group activation, recipient
identity, and strict-versus-frontier capacity allocation. If `S1` reproduces
the `B1` frontier gain and retention loss, curriculum rotation is sufficient;
an additional `B1-S1` gain identifies behavior-specific successor alignment.
Per-operation attempted, mixed, shipped, and trainable group shares must be
reported to test this mechanism rather than inferred from endpoint curves.

### Accepted-update singularity in iterative SFT and RL

There is a sharper perfect-versus-imperfect distinction when the algorithm
collects a fixed number of accepted samples or optimizer updates instead of
fixing raw environment exposure. Let `Z_p` be proxy acceptance and define

```text
q = P(R = 1),       h = P(A, R = 0).
```

For a trajectory `tau`, rejection-sampling SFT trains on

```text
P_p(tau | Z_p = 1)
  = P(tau) [R(tau) + p A(tau) (1 - R(tau))] / (q + p h).
```

If a hard stratum is strict-dead, `q = 0`, then for every `p > 0`,

```text
P_p(tau | Z_p = 1) = P(tau | A, R = 0).
```

The conditional training distribution is independent of the magnitude of
`p`. The defect rate controls only the expected raw sampling cost,
`1 / (p h)`, while `p = 0` produces no accepted sample at all. Thus fixed-count
iterative SFT has an exact support discontinuity at a perfect verifier even
though the probability of seeing any defect in a fixed raw bank remains the
smooth curve `1 - (1 - p h)^N`.

The result is stronger with several defect behaviors. If strict-wrong class
`A_i` has prevalence `h_i` and false-positive probability
`p_i = epsilon c_i`, then at `q = 0`,

```text
P(A_i | Z = 1) = c_i h_i / sum_j c_j h_j,       epsilon > 0.
```

Taking the verifier's aggregate error scale `epsilon` arbitrarily close to zero
does not remove its relative selection bias; it only makes accepted examples
more expensive to obtain. The *shape* of the defect across behaviors, rather
than aggregate FPR, determines the limiting SFT curriculum.

The GRPO analogue follows by conditioning on an activated strict-dead group.
As `p -> 0+`, almost every activated group contains one false positive. Its
positive centered advantage tends to `(G - 1) / G`, and the conditional prompt
distribution is size-biased by its eligible count `K`. Hence an accepted
optimizer step remains order one and has a nonvanishing limiting direction;
only the wait between steps diverges. When at least one clean-active stratum is
mixed into training, the hard-stratum share instead vanishes with `p`, so the
singularity is localized to strict-dead support rather than universal.

This yields a dual-clock falsification experiment. On a frontier-only stratum
with measured `q` below a fixed bound and `h > 0`, sweep log-spaced `p` values
including zero and report both:

- fixed raw-rollout exposure, where activation must collapse against `N p h`
  and approach the clean arm smoothly;
- fixed accepted examples or optimizer steps, where all sufficiently small
  positive doses should have the same recipient composition and update
  direction while raw cost scales as `1 / p`.

For iterative SFT, train identical optimizer schedules on a fixed accepted
count and compare behavior-conditioned with reward-count-matched shuffled
recipients. For RL, repeat with exact attempted-slot accounting and the same
group-size controls. Failure of small positive doses to collapse after
conditioning on accepted count rejects the strict-dead approximation or shows
policy feedback before the proposed limit. This is an algorithmic support
singularity, not evidence by itself for a thermodynamic phase transition.

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

The later descriptive refresh at `E_log_proxy = 552,192` preserves and sharpens
the non-monotonic pattern:

| Arm | OP11--12 endpoint | OP13--17 endpoint | OP15--17 endpoint | OP15 endpoint | OP15--17 normalized AUC | OP11--12 normalized AUC |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0% | 51.02% | 18.18% | 6.74% | 15.51% | 1.96% | 51.20% |
| 1% | 40.66% | 18.55% | 10.78% | 20.44% | 4.03% | 45.38% |
| 5% | 39.75% | 15.50% | 6.67% | 12.00% | 1.86% | 45.14% |

The interpolation brackets are steps 400--425 for 0%, 700--725 for 1%, and
step 975 for 5%. The 1% frontier AUC is 2.06 times clean and 2.17 times 5%,
while its OP11--12 retention remains 10.54 points below clean. The artifact is
explicitly labeled `descriptive-v2`: its exposure is a periodic log proxy and
its online epochs mix policy versions. It motivates the matched frozen-policy
study but cannot establish the effect causally.

A later refresh at the common log-proxy exposure `E_log_proxy = 859,008`
continues the same inverted-U frontier pattern over a longer interval:

| Arm | OP15--17 normalized AUC | OP15--17 endpoint | OP11--12 normalized AUC | OP11--12 endpoint | sustained OP15 discovery exposure |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0% | 4.77% | 12.15% | 51.30% | 46.44% | 382,208 |
| 1% | 7.34% | 12.50% | 43.86% | 38.25% | 310,400 |
| 5% | 4.83% | 9.68% | 45.35% | 44.06% | 428,160 |

The 1% arm has 1.54 times the clean frontier AUC and reaches the post-hoc
sustained OP15 criterion earlier, but it retains 8.19 points less OP11--12
performance at the common endpoint. The 5% arm loses the frontier benefit and
discovers OP15 later than clean. Within this descriptive interval, the result
is inconsistent with a simple monotone "more corrupted reward causes
proportionally more damage" description and is consistent with a
low-dose frontier accelerator plus a separate retention/distortion cost. It
does not distinguish recipient-specific successor alignment from generic
group activation; that distinction is the preregistered `B1-S1` contrast.
The machine-readable artifact is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/verifier-defect-descriptive-20260807-0345/summary.json`
(SHA-256 `df17bb608b32a569cdd072e3aaa9bc846e4b3d1ea15f7e55f0f08f122bc11cd5`).
It remains a one-seed, mixed-policy, periodic-log-proxy analysis.

### Direct shipped-cohort curriculum audit

A deterministic parse of every stat-stable saved training cohort through the
first 900 optimizer steps reconstructs complete 128-row prompt groups and
checks the reward algebra row by row. The common-window result is:

| Arm | complete groups | proxy-mixed groups | strict-mixed | defect-only mixed | mean OP among mixed | OP21--40 share among mixed |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0% | 3,600 | 1,125 | 1,125 | 0 | 12.63 | 0.0% |
| 1% | 3,582 | 1,313 | 734 | 579 | 18.41 | 29.9% |
| 5% | 3,509 | 1,505 | 419 | 1,086 | 22.04 | 50.2% |

Here *defect-only mixed* means that every strict reward in the group is zero,
but one or more candidate coins make the proxy reward vector mixed. Across all
393 such OP21--40 mixed groups at 1% and all 756 at 5%, the verifier defect is
therefore the exact reason the group carries a GRPO gradient; the clean arm has
no mixed OP21--40 group in the same step window. Over 1,982,976 audited rows,
there are zero mismatches in reward-versus-proxy, candidate definition,
Bernoulli trigger, or proxy composition.

The time split identifies dose-dependent persistence, but not clean takeover.
From steps 0--299 to 600--899, the 1% arm's defect-only groups fall from 241 to
154 while strict-mixed groups rise from 203 to 280; its hard share among mixed
groups falls from 36.9% to 24.0%. At 5%, defect-only groups instead remain 349
versus 369 and the hard mixed share stays 53.0% versus 50.5%. Raw sampled
hard-task share is nearly flat within each arm over the same windows, so the
rotation occurs in the gradient-bearing subset rather than through a changing
source sampler. However, OP21--40 contains zero strict-positive rows in every
arm through step 899. The 1% pattern therefore establishes partial decay of a
defect-dependent frontier, while the 5% pattern establishes persistence; it
does not establish that candidate trajectories converted into strict ones.

This identifies the mechanical cause of the curriculum rotation inside saved
groups, but not its population prevalence. Legacy V2 saves 512-row cohorts only
when an attempt ships; wholly empty attempts, errored rows, and some fragments
are absent. The audit excludes 1.50% of saved 1% rows and 2.31% of saved 5% rows
whose task index does not form an exact 128-row group. It therefore estimates a
shipped-cohort-conditional mechanism, not the full attempted-group rate or the
recipient-specific causal effect. The sealed confirmatory logs include those
missing attempts and are analyzed on raw-attempt time.
The complete cutoff-pinned artifact is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/verifier-defect-curriculum-20260807-040522/summary.json`
(SHA-256 `263f20da309fdccc5f1a9916519ba6b4575f0183ea3f64c6e2a4991aedd770ea`;
analysis-manifest SHA-256
`0954674d64afd6dee7a67ba0de8c5c11accbc0402a8558c5daab5c644efeae17`).

### Clock and strict-emergence correction

The apparent 1% frontier benefit depends on which training clock is held fixed.
Exposure AUC integrates the evaluation curve against the logged raw-rollout
proxy through `E = 859,008`; step AUC integrates the same complete evaluations
against optimizer step through the common step `T = 875`:

| Metric | 0% | 1% | 5% |
| --- | ---: | ---: | ---: |
| OP15--17 exposure AUC | 4.7705% | 7.3427% | 4.8273% |
| OP15--17 step AUC | 6.6690% | 5.8476% | 1.3976% |
| OP11--12 step AUC | 50.9000% | 43.9714% | 45.9929% |
| optimizer steps at `E = 859,008` | 721.1 | 1200.0 | 1541.2 |
| logged exposure at step 875 | 995,456 | 653,568 | 496,384 |

The 1% contrast therefore reverses from `+2.572` points at fixed raw exposure to
`-0.821` points at fixed update count. False positives rescue otherwise
zero-advantage groups, so the 1% arm obtains about 1.66 times as many optimizer
updates as clean by the common exposure. The existing result supports greater
accepted-update throughput per raw rollout, not better strict learning per
optimizer update. It remains possible that the recipient identity improves or
harms those rescued updates relative to a shuffled recipient; that is the
preregistered `B1-S1` contrast.

Saved OP15--20 groups give the same dose ordering. The repeated cross-sectional
strict share `S / (S + K)` among answer-correct rows and the counts of
strict-mixed versus defect-only groups evolve as follows:

| Arm | strict share, steps 0--299 -> 300--599 -> 600--899 | strict-mixed / defect-only groups |
| --- | ---: | ---: |
| 0% | 5.37% -> 25.65% -> 33.34% | 17/0 -> 85/0 -> 122/0 |
| 1% | 0.04% -> 14.39% -> 22.35% | 1/52 -> 50/48 -> 86/40 |
| 5% | 0.00% -> 0.31% -> 11.23% | 0/59 -> 3/85 -> 19/86 |

The first saved strict-positive OP15--20 group occurs at step 115 for clean,
285 for 1%, and 522 for 5%, approximately exposures 209,536, 248,192, and
302,848. Thus clean strict emergence is earlier on both saved clocks. Strict
evaluation can become nonzero before the first strict training group because
evaluation samples a different prompt bank and policy generation; this is
transfer or sampling, not observed conversion of a particular candidate.

At OP21--40, all arms have zero strict-positive rows through step 899. From the
early to late window, 1% candidate-row mass falls from 17.12% to 13.18% and its
defect-only/raw-group rate falls from 23.03% to 14.84%. At 5%, candidate mass
rises from 14.92% to 17.48% and defect-only groups remain 33.33% versus 34.83%.
The first later hard strict row appears at step 915 for clean and 1169 for 1%; no
hard strict row appears at 5% through its frozen step 1631. This supports a
dose-ordered delay and a persistent high-dose defect frontier, not faster
candidate-to-strict conversion at 1%.

The saved-cohort activation rate is itself selected. Among eligible zero-strict
groups through step 899, 1% has 579 activated of 1,542 saved groups (37.55%),
while the unconditional mixed-gate sum
`sum_g [1 - (1 - p)^K_g - 1[K_g = V_g] p^K_g]` predicts 448.27 (29.07%). At
5%, the analogous values are 1,086 of 1,600 (67.88%) versus
1,056.88 (66.06%). The low-dose excess is expected survivor conditioning: a
rare trigger often makes an otherwise absent all-zero batch shippable. The
realized row-level trigger rates, 1.169% and 5.070%, agree with the configured
coins. Population activation and nucleation hazards require the full attempt
logs because the legacy dumps omit rejected all-zero attempts.
The reproducible dual-clock artifact is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/verifier-defect-threshold-audit-20260807-044642/summary.json`
(SHA-256 `908829f365a8311caa38cc5520c8b75f3ef0a0af09d2c939ceb620005df4b949`;
analyzer SHA-256
`e9f2d9b5e548c3f13a5f8b12c62fff2072fbf3888d448450023a13abb2152cdb`).

The optimized-batch diagnostics are directionally consistent with low-dose
defect decay, not by themselves with self-purification. Comparing the first and
latest 100 logged batches, the 1% arm's candidate mass falls from 22.11% to
17.89%, while realized defect triggers fall from 3.6% to 1.6% of proxy-positive
rewards. In the 5% arm, candidate mass is 18.58% early and 18.92% late, while
defect triggers remain 8.7% of proxy positives after starting at 19.6%.
Strict-positive mass in those batches rises from 7.39% to 12.36% at 1% and from
3.92% to 9.74% at 5%. These W&B aggregates cover post-filter batches rather
than every generated group, so they are mediator timing evidence, not unbiased
prevalence estimates or longitudinal candidate-to-strict transitions. The
matched group audit is designed to confirm or reject this pattern on the full
population.

As an exploratory time-to-discovery statistic, requiring OP15 strict pass@1 to
remain at or above 10% for three consecutive evaluations is first met after
382,208 generated rollouts at 0%, 310,400 at 1%, and 428,160 at 5%. The
threshold was selected after inspecting the curves, so it is a mechanism
diagnostic rather than a preregistered endpoint. Confirmatory runs use the
fixed rule above rather than selecting a new threshold from their curves.

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

Static conditional advantage is not enough to predict this effect. Write

```text
J(theta) = P_theta(R = 1),       H(theta) = P_theta(A, R = 0),
dot(theta) = grad J(theta) + p grad H(theta).
```

Under the gradient-flow approximation, strict performance initially changes as

```text
dot(J) = ||grad J||^2 + p <grad J, grad H>.
```

Every `A` trajectory is wrong under the strict verifier, yet the cross-gradient
`<grad J, grad H>` can be positive when producing an answer-correct but
reasoning-wrong trajectory exercises parameters or latent computations also
needed for fully correct solutions. Call this quantity *successor alignment*:
it measures whether selecting a behavior now moves the policy toward future
strict success, rather than whether that behavior is currently correct. Its
sign may change along training, giving a concrete route to a low-dose benefit
and high-dose harm without contradicting the fact that `A` has zero strict
reward.

This is stronger than contemporaneous conditional advantage. The systematic-FP
analysis of Egashira et al. measures whether trigger-bearing samples already
have above-average oracle reward in the current rollout group. Here `A` is
strict-wrong by construction, so its current strict advantage is nonpositive:
zero in an all-wrong group and negative when a strict success is present.
Nevertheless, rewarding `A` can have positive successor alignment if its
parameter update raises the probability of later strict solutions. The frozen
recipient-swap assay tests this future-directed gradient effect, which cannot be
identified from initial trigger frequency or current oracle conditional
advantage alone.

The per-group shuffled control is a conservative direct test. Within every
realized group, its saved behavior and shuffled counterfactual vectors have the
same reward histogram: behavior assigns the extra positives to `A`, while
shuffling assigns them among all strict negatives. `B1` and `S1` are independent
online runs, however, so they need not sample the same groups, candidate
opportunities, or realized `H`. Report those divergences rather than claiming
cross-run histogram identity. A shuffled recipient can itself be `A`, which
attenuates rather than reverses the recipient-identity contrast. `B1 > S1`,
followed by conversion of candidate mass into strict success after defect
removal, is evidence consistent with positive successor alignment. A null
result is weaker: it may reflect this overlap or averaging useful and
destructive subclasses of `A`.

The sharper mechanistic assay is a disjoint reward-recipient swap from one
frozen checkpoint and immutable rollout bank. For every eligible group, pair an
answer-correct/strict-wrong trajectory `a` with an answer-wrong/strict-wrong
trajectory `w`; match length, mean rollout log probability, entropy, finish
reason, and truncation. Replay the exact tokenized batch, optimizer state,
scheduler state, packing, masks, and RNG state in two branches, changing only
which member receives one extra reward. Because the group reward histogram is
identical, the per-pair update contrast is

```text
grad J_A - grad J_W = grad log pi(a) - grad log pi(w).
```

The primary one-step endpoint is the paired change in canonical strict-solution
log likelihood on unseen prompts; common-seed strict pass@1 is secondary and
requires thousands of rollouts for percent-scale effects. Run this first with
one swapped reward per eligible group, then with the realized `H` from the 1%,
5%, 10%, and 20% rules. A stronger subclass contrast pairs near-executable,
low-graph-mismatch `A` against deterministically corrupt or non-executable `A`.
This separates a reasoning precursor from generic final-answer imitation.

The defect can also be *self-purifying*. Among proxy-positive trajectories at
difficulty `d`, the expected defective fraction is

```text
phi_d(p, t) = p h_d(t) / (q_d(t) + p h_d(t)).
```

Initially `q_d` may be nearly zero, so almost every positive at the hard frontier
is defective. If those updates have positive successor alignment, they increase
`q_d`; once `q_d >> p h_d`, clean positives take over and `phi_d` falls. A low
dose has a reachable clean-takeover threshold, while a high dose raises that
threshold and can trap training in the precursor basin. This predicts an early
peak and then decline in candidate-trigger share for a successful low-dose run,
but persistently high trigger share for a plateauing high-dose run.

The 18,000 base-policy OP11--40 calibration trajectories make this regime
concrete. At OP13, `q = 0.00167` and `h = 0.24667`, so defective trajectories
constitute about 59.7% of expected positives at 1% and 88.1% at 5%. For OP14--20,
no strict success appeared in 600 samples per operation while `h` remained
13.5--21.7%. With group size 128, 1% activates approximately 15.9--24.2% of
those otherwise all-zero hard groups; 5% activates 58.0--75.2%. Thus “1% verifier
error” does not mean 1% contamination of the learning signal at the frontier.
The matched audit records will test whether those initially defective positives
convert into strict reward or merely reproduce themselves.

There is also a genuine singularity at a perfect verifier under an
optimizer-step budget. For a hard stratum with `q_x = 0`, `p = 0` gives no
retained update from that stratum, while any `p > 0` eventually yields one if
sampling retries continue indefinitely. The expected raw-rollout cost diverges
as approximately `1 / (G h_x p)`. Thus fixed optimizer-step experiments can
show a discontinuity between perfect and arbitrarily imperfect verification,
whereas fixed raw-exposure experiments must show the smooth finite-budget
crossover below. Reporting both clocks distinguishes a real support change from
an accounting artifact.

More generally, if clean-success probability decreases approximately as
`q_d = q_0 exp(-alpha d)` while hackable behavior remains nonzero, the two proxy
terms cross near

```text
p_c(d) = q_d / h_d,
d_c(p) ~= log(q_0 / (p h_d)) / alpha.
```

Every `p > 0` then creates a finite *verification horizon* beyond which the
proxy contribution dominates, whereas `p = 0` has no such finite horizon. This
is a precise sense in which a perfect verifier can differ qualitatively from an
arbitrarily accurate imperfect one. Sweeping operation count and plotting the
frontier against `log p` tests the predicted logarithmic horizon; hysteresis is
still required before calling the finite-run crossover a phase transition.

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

### Randomized-innovation test for self-excitation

The simulated verifier coin provides a within-run causal instrument. Index the
fixed 512-row pre-filter batch attempts by raw attempt time `t`, including
attempts that become empty after the enforced zero-advantage filter. Let

```text
K_t = number of eligible A slots in the fixed attempt,
H_t = number of those slots whose behavior coin is below p,
Q_t = H_t - p K_t,
V_t = p (1 - p) K_t.
```

Conditional on the complete pre-coin trajectories and attempt composition
`F_t`, the hash coin gives

```text
E[Q_t | F_t] = 0,       Var(Q_t | F_t) = V_t.
```

This identity fails if repeated `sample_slot` keys reuse the same coin without
accounting for their covariance, so the confirmatory analyzer rejects repeated
keys. It also verifies that no enforced pre-batch filter depends on reward.
`analyze_verifier_causal_attempts.py` reconstructs exact group slices, binds
its inputs and implementation by SHA-256, and emits `S/K/H/Q/VQ` for every
attempt.
Shipping, optimizer-step advancement, and later policy adoption are downstream
of `H_t`; restricting to shipped batches or indexing the primary analysis by
optimizer step would condition on treatment and destroy the randomization.

For a future outcome `Y_(t+l)` measured at a fixed raw-attempt lag, estimate the
additive response per extra false reward with the design denominator

```text
beta_l = sum_t Q_t [Y_(t+l) - m_l(F_t)] / sum_t V_t,
```

and report the instrumental-variable check

```text
beta_l_IV = sum_t Q_t [Y_(t+l) - m_l(F_t)] / sum_t Q_t H_t.
```

The adjustment `m_l` may use only pre-coin variables: strict count, candidate
count, operation mix, raw-attempt/time bin, and current policy-version mix.
Primary lags are fixed in advance; negative-lag placebo outcomes must be null.
Weak randomized variation `sum V_t`, the fraction of later rows actually
generated by the updated policy, and empty/shipped status are reported as
diagnostics or mediators, not selection criteria.

There is a second exact innovation for the race to a trainable group. For a
complete group with `V` valid advantage rows, `S` strict positives, and `K`
eligible candidates, its mixed-reward probability is

```text
pi_g = 1 - 1[S = 0] (1 - p)^K - 1[S + K = V] p^K.
```

If `M_g` records whether the realized proxy rewards are mixed, then
`W_g = M_g - pi_g` is mean zero with variance `pi_g (1 - pi_g)`. On a
strict-dead group with `K < V`, `pi_g = 1 - (1-p)^K`. The conditional survival
curves to the first hack and first trainable bridge are respectively
`(1-p)^(cumulative K)` and the cumulative product of `(1-pi_g)`. These separate
rare-event nucleation from the effect of which trajectory receives the reward.

Use future eligible-candidate count as the self-excitation outcome and call its
lag response `lambda_l`. Over a predeclared horizon `L`,

```text
R_L = p * sum_(l=1)^L lambda_l
```

is the empirical reproduction number of the defect. `R_L < 1` predicts a
finite multiplier approximately `1/(1-R_L)`; `R_L > 1` predicts supercritical
growth until policy or task saturation. Estimate this separately in behavior
and shuffled arms: `lambda_B-lambda_S` tests recipient identity, while the
strict-count impulse response tests whether extra `A` reward converts into
future strict success. A rolling-window lower bound above one is evidence of a
self-exciting regime, but a phase-transition claim still requires multiple
seeds, a predeclared crossing rule, and persistence or hysteresis after the
defect is removed.

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
H_p = number(candidate and U < p),
P_p = number_strict + H_p.
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
same realized number `H` of extra positives that the behavior-conditioned rule
would produce, then assign exactly `H` rewards uniformly among all strict-negative
rollouts. This matches group reward mean, variance, and zero-advantage status;
only the association between reward and `A` changes. Run behavior and shuffled
arms through the same group-scoring path so partial-group error handling is also
matched.

The first 500-step one-seed mechanism screen has five arms: group-scored clean `C0`,
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

where AUC is indexed by raw attempted-slot exposure (`sum(target_size)`). The stepping-stone
requirement is `B1 > S1` and an earlier interval-censored sustained OP15
discovery time. The distortion requirement is `B5 < S5` on OP13--17 AUC and
OP11--12 retention. Sustained OP15 discovery is the first checkpoint beginning
three consecutive evaluations with strict OP15 pass@1 at least 10%, dated at
the first checkpoint's raw exposure.

The primary exposure interval is fixed before matched-run results exist:

```text
E* = 256,000 attempted training slots.
```

This is the minimum shipped exposure for 500 optimizer updates of 512
trajectories and is therefore covered by every completed arm; attempted slots
are at least this large, while discarded or errored groups increase them.
Evaluate immutable policy
checkpoints at steps `0, 25, 50, ..., 500`, linearly interpolate the two
checkpoints bracketing `E*`, and compute the primary AUC on `[0, E*]`. A missing
scheduled frozen evaluation inside that bracket invalidates the confirmatory
comparison rather than being bridged or silently skipped.

The live in-training evaluator currently mixes adjacent policy versions after
the eval queue drains, so those curves are descriptive only. All five pilots
retain stable weights every 25 steps. Confirmatory endpoints use frozen
checkpoint OP11--45 evaluations and exact exposure clocks reconstructed from
`train_group_stats.jsonl`. Mixed-policy live epochs are excluded from the
confirmatory dataset rather than assigned to a checkpoint policy.

Before analysis, resolve and validate exactly the `C0/B1/S1/B5/S5` arm set from
the saved orchestrator and trainer configs: common base model and OP10--40
training dataset, seed `20260805`, group size 128, 500 optimizer steps,
`sample_slot` draws, and the preregistered assignment/rate for each label. Audit
every saved group so the optimized reward equals its configured behavior or
shuffled proxy vector and the two counterfactual vectors have equal histograms.
After removing only treatment, output-path, and W&B metadata, normalized hashes
of the complete resolved orchestrator, trainer, and inference configs must agree
across arms. Each run must also carry a sealed `source_provenance.json`: its
launch hashes must still match `rl.sbatch` and the resolved configs, while the
parent commit, submodule SHAs, runtime-source digest, `uv.lock`, and pip-freeze
identities must agree across arms. The seal also binds the bytes of every
train/eval dataset, the base model, tokenizer, and chat template. Each 128-slot
group must contain exactly one sample ID and operation; report unique and
repeated prompts plus the ordered sample/op prefix and positional match rates
for each independent behavior/shuffled pair.
The exposure report separates attempted, received, valid, advantage-population,
assembled, shipped, and trainable-shipped slots, and requires shipped optimizer
steps to be contiguous through the checkpoint bracketing `E*`.

Frozen evaluation must use the strict OP11--45 contract and identical canonical
step-0 generation digests across all five arms, not merely equal aggregate
scores. The analyzer reconstructs the generation contract from the sealed
model, datasets, prompt sequence, sampling settings, semantic inference config,
and pinned evaluator/scorer contents, then requires the manifest, completion
record, and metrics provenance to match it. It deterministically re-scores every
generation and rejects altered or stale strict-result rows.
The analysis emits the preregistered interaction and its two component
contrasts. Passing this audit makes the single-seed result a valid mechanism
screen; it does not make it a causal-effect estimate or phase-transition claim.

This shuffled control removes the recipient-level association between `A` and
reward conditional on realized `H`, but `H` is still drawn from the eligible
candidate count `K` in that same group. It identifies the effect of allocating
a behavior-dependent reward budget to the candidate traces rather than randomly among strict
negatives. Its random recipient can itself be `A`, so it is an attenuated
contrast rather than a disjoint `A`-versus-non-`A` swap. The one-step paired
recipient assay above removes that overlap. A fully exogenous control would
instead require `H` from an independent donor group and would no longer exactly
match every realized group histogram.

### 4. Group-size scaling

Test the low-load pairs `(G,p) = (128,1%), (32,3.940399%)` and high-load
pairs `(128,5%), (32,18.549375%)`, keeping 512 trajectories per nominal batch.
The exact smaller-group rate is

```text
p_32 = 1 - (1 - p_128)^4,
```

which makes `(1 - p_32)^(32 h) = (1 - p_128)^(128 h)` at fixed eligible
prevalence `h`; `4 p_128` is only its small-rate approximation. Record raw
exposure `E=sum G`, realized triggers `H=sum H_g`, mixed groups
`M=sum 1[group trainable]`, and normalized corrupt dose `D=sum H_g/G`.
Frontier discovery collapsing against `H` supports nucleation; behavior and
shuffled arms collapsing against `M` supports generic group activation; a
behavior-minus-shuffled loss tracking `D` supports recipient-aligned
distortion.

Then distinguish finite-budget nucleation from a nonzero critical defect rate.
Use `G in {32, 64, 128}`, at least three raw-exposure budgets, and a log-spaced
conditional-dose grid around each observed crossover. Let `p50(E,G)` be the
dose at which half the seeds reach the preregistered sustained frontier event.
The independent-bridge null predicts curve collapse against `E h p`,
`p50 proportional to 1/E`, and a crossover that moves toward zero as exposure
grows. A genuine nonzero critical line requires `p50` to approach a positive
limit, transition width to narrow with scale, and seed outcomes to become
bimodal near that limit. Without those signatures, report nucleation rather
than a phase transition.

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

Also run bidirectional `p` staircases with equal raw exposure at every rung:
strict-to-high-to-strict and high-to-strict-to-high. Compare policies at the
same current `p`, exposure, and direction, and add an optimizer-state reset
control at each turn. A basin transition predicts a nonzero loop area that does
not vanish when rung dwell time is increased, plus incomplete recovery during
the final `p=0` washout. A loop removed by resetting Adam is optimizer-state
memory rather than a persistent policy basin.

### 6. Frozen recipient susceptibility and pulse scaling

At identical frozen checkpoints, pair each strict-wrong candidate `A` with an
answer-wrong strict-negative trajectory `W` matched on length, log probability,
entropy, truncation, and operation. Replay identical batches and optimizer/RNG
state while swapping one extra reward between `A` and `W`. For difficulty `d`,
measure

```text
chi_d = <g_A - g_W, g_strict,d>,
```

where `g_strict,d` is the gradient of canonical strict-solution log likelihood
on unseen OP`d` prompts. Repeat one, two, four, and eight matched reward pulses
before common-seed strict generation. Positive susceptibility localized near
the frontier, followed by candidate-to-strict conversion, supports a stepping
stone; negative susceptibility supports distortion. A nonlinear pulse
threshold, critical slowing near that threshold, and a state that persists
after rewards return to strict provide a sharper basin-transition test than
endpoint pass rates alone.

### 7. Persistence and location of corruption

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
- [Cai et al., *Reinforcement Learning with Verifiable yet Noisy Rewards under
  Imperfect Verifiers* (2025)](https://arxiv.org/abs/2510.00915) and [El
  Mansouri et al., *Noise-corrected GRPO: From Noisy Rewards to Unbiased
  Gradients* (2025)](https://arxiv.org/abs/2510.18924) derive corrections for
  Bernoulli reward channels with estimable class-conditional flip rates. Those
  corrections do not remove an endogenous behavior-conditioned term whose
  frequency changes with the policy.
- [Lv et al., *The Climb Carves Wisdom Deeper Than the Summit: On the Noisy
  Rewards in Learning to Reason* (2025)](https://arxiv.org/abs/2505.22653) show
  that rewarding reasoning phrases alone can sometimes produce strong strict
  downstream performance. This is evidence that an imperfect proxy can select
  a useful precursor, but it does not identify the effect against a
  reward-histogram-matched recipient shuffle or map the low-dose crossover.
- [Shao et al., *Spurious Rewards: Rethinking Training Signals in RLVR*
  (2025)](https://arxiv.org/abs/2506.10947) find that random or even negatively
  correlated rewards can improve some Qwen math models by amplifying
  high-prior behavior through clipping bias, while failing on other model
  families. [Chen et al., *Exploration vs Exploitation: Rethinking RLVR through
  Clipping, Entropy, and Spurious Reward*
  (2025)](https://arxiv.org/abs/2512.16912) further analyze this mechanism, and
  [Zhu and Kang, *Noisy Data Is Destructive to Reinforcement Learning with
  Verifiable Rewards* (2026)](https://arxiv.org/abs/2603.16140) show that some
  apparent robustness disappears after re-verifying contaminated annotations.
  Consequently, `C0-S1/S5` measures generic algorithmic effects of spurious
  group rewards, while `B1-S1` and `B5-S5` isolate which trajectories receive
  those otherwise identical advantages.
- [Plesner et al., *An Imperfect Verifier is Good Enough: Learning with Noisy
  Rewards* (2026)](https://arxiv.org/abs/2604.07666) find small peak-performance
  losses under noise rates up to 15% across code and science, while [Rahman et
  al., *When Can LLMs Learn to Reason with Weak Supervision?*
  (2026)](https://arxiv.org/abs/2604.18574) connect weak-supervision
  generalization to delayed reward saturation and initial reasoning
  faithfulness. Together they motivate separating random-channel robustness
  from behavior-specific successor alignment.
- [Egashira et al., *Delay, Plateau, or Collapse: Evaluating the Impact of
  Systematic Verification Error on RLVR* (2026)](https://arxiv.org/abs/2605.02909)
  compare iid flips with deterministic behavior-triggered errors and clean-verifier
  alternation. They show that initial trigger frequency and contemporaneous
  oracle conditional advantage predict delay, plateau, or collapse. The present
  novelty must therefore come from low-rate conditional scaling, exact
  group-histogram controls, OOD strict-CoT difficulty, one-time washout/path
  dependence, or successor alignment of a currently strict-wrong precursor
  rather than the generic claim that systematic errors differ from random noise.
- [Helff et al., *LLMs Gaming Verifiers: RLVR can Lead to Reward Hacking*
  (2026)](https://arxiv.org/abs/2604.15149) show that extensional verification
  induces instance-enumeration shortcuts whose prevalence rises with task
  complexity and inference-time compute, while isomorphic verification removes
  them. Difficulty-correlated verifier exploitation is therefore not itself a
  novel claim; the open question here is the conditional-dose critical line and
  the dynamics under an exactly reward-histogram-matched recipient control.
- [Khalifa et al., *Countdown-Code: A Testbed for Studying The Emergence and
  Generalization of Reward Hacking in RLVR*
  (2026)](https://arxiv.org/abs/2603.07084) find that 1% reward-hacking
  contamination in distillation SFT can be internalized, amplified by later RL,
  and generalized out of domain. This overlaps the motivating claim that a
  small seed can have a large downstream effect, but its intervention is SFT
  trajectory contamination rather than a randomized online verifier defect.
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
