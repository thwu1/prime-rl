# Correlated verifier-defect Stage-1b preregistration

Status: locked before GPU submission. None of the six G/T overlays in this
directory has been submitted. This is an exploratory causal screen, not a
confirmatory phase-transition experiment.

## Question and intervention

The target behavior is

```text
A = answer-correct and strict-CoT-wrong.
```

Every defect reward is assigned to A itself. The nominal candidate marginal is
`p=1/400`, the gate probability is `alpha=1/3`, and an open gate uses
`q=p/alpha=3/400`.

- **I:** candidates trigger independently with probability `p`. The I arm is
  the same seed's B, `L=128`, `p=0.0025` arm from `masked_activation_v1`; it is
  not duplicated here.
- **G:** a domain-separated hash of `(defect_seed, sample_id)` opens each group
  independently with probability `alpha`; open-group candidates use q.
- **T:** exactly one of the three visible GSM-Infinite templates is vulnerable
  in a run; its candidates use q and all other templates have zero defect
  probability. Seeds 20260805, 20260806, and 20260807 select
  `crazy_zootopia`, `movie_festival_awards`, and `teachers_in_school`,
  respectively.

Over the randomized gate or three-seed Latin-square template assignment,

```text
P(trigger_j | candidate_j) = p
E[H | C] = C p.
```

G and T have the same randomized law for one fixed group. Both are
behavior-correlated and can reinforce A. The primary difference is that only T
adds a persistent prompt feature that predicts whether A is susceptible to the
verifier defect. G is therefore a control for equal marginal reward and
within-group burstiness, not an “unlearnable behavior” control.

The selected T template has conditional rate q within a realized run, so its
per-run total reward exposure need not equal G exactly. Template candidate-mass
imbalance and realized deterministic G gates are prespecified manipulation
diagnostics, not reasons to retune seeds or rates.

## Experimental units and reused arms

The downstream experimental unit is one trained policy. The three inference,
defect, and template-assignment seeds form paired blocks. Prompt order remains
the common seed 42. Rollout groups, candidates, and defect events are mechanism
observations and do not increase the number of independent policies.

The scientific four-arm screen is C0/I/G/T. C0 and I are byte-reused from the
masked Stage-1 matrix. This directory adds only three G-B and three T-B runs.
No L1 or all-or-none GPU arm is part of Stage 1b. L1 has little additional
activation at this horizon, while all-or-none has too few effective events.

## Clocks and clean outcomes

Every arm uses the same physical 128-rollout GRPO group and continues until it
has reached both 1,500 shipped updates and 12,000 finalized groups at a retained
50-update boundary. Hard guards are 3,000 updates and 20,000 groups.

Analyze two clocks separately:

1. `U1500`: the exact retained 1,500-update checkpoint;
2. `G12000`: the last retained 50-update checkpoint at or below 12,000 audited
   attempted groups.

The joint-stop checkpoint is not a common causal clock. Report raw attempts,
shipped updates, trainable tokens, and normalized strict AUC on both clocks.

The optimized reward is the proxy. Every performance claim uses clean strict
dependency-graph scoring from saved single-policy checkpoints on the same 200
held-out prompts for each OP11--45 operation. Fixed outcome bands are:

- OP11--20 retention/bridge;
- OP21--40 in-distribution hard target;
- OP41--45 unseen extrapolation target.

For every band also report answer correctness and
`A = answer-correct and strict-wrong`. Stratify T and its paired G arm by the
template selected in T versus the other two templates. A prevalence is a
co-primary mechanism readout because strict OP41--45 can remain at a zero
floor.

## Prespecified contrasts

For seed block s, outcome band b, and clock c, define:

```text
theta_TG[s,b,c] = Y_T[s,b,c] - Y_G[s,b,c]
theta_GI[s,b,c] = Y_G[s,b,c] - Y_I[s,b,c]
theta_TI[s,b,c] = Y_T[s,b,c] - Y_I[s,b,c]
```

`theta_TG` is primary: persistent, visible susceptibility versus a
prompt-random, non-legible gate at matched randomized one-group law. G's hash
is deterministic for an exact sample ID, but prompts are unique in training,
so its state is not a reusable prompt feature. `theta_GI` tests group
clustering without persistent task correlation. `theta_TI` is the total
persistent-gate contrast and is secondary.

The selected-template interaction is

```text
psi_TG = (Y_T,selected - Y_T,unselected)
         - (Y_G,same-template - Y_G,other-templates).
```

Compute it separately for strict correctness and A prevalence. The template
selected in T defines the same partition for its paired G arm. Do not pool
templates first and choose a partition afterward.

## Mechanism audit

Independently replay, for every finalized group:

- physical and valid slots, strict positives S, candidates C, and mask L;
- the group-gate hash or selected-template equality;
- gate-open state, nominal p, conditional q, and candidate coins;
- behavior trigger count H and the selected B/S/M recipient vector;
- proxy reward, mixed-group activation, batch attempts, and stopping clocks.

Report gate-open groups, candidate mass behind open gates, expected and realized
H, expected and realized activations, and all quantities by operation and
template. G's realized open fraction and open candidate mass must be shown for
each seed. T's finite template imbalance must be shown rather than normalized
away. Policy-dependent C and H are mediators and must not be regression-adjusted
to manufacture marginal equality after training.

The step-zero preflight must bind the frozen strict bank, final runtime,
replay analyzer, and config contract by SHA-256. It is an in-distribution
base-policy calibration, not a prediction after policy feedback.

The corrected locked artifact is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/correlated-defect-preflight-v2/report.json`
(SHA-256
`680c5bf3dd441a7b26da685532f60d3c04af3f69b422088bc25a89a50a263d9d`;
payload SHA-256
`8715aa515a353f99ac68c07c9fff6b4b05bd379eb592b90d80edafdad22bd9b0`).
It binds analyzer SHA-256
`1f397b89ae969bbf393a7a8c7dc71f5355b464276501746120cd4a39c19f4449`,
runtime SHA-256
`35818ce97474a60fc5f78796b805969e3a0cb13eab50c3aceb4d4f47df9199c5`,
live replay SHA-256
`8dd35a1c1f3ff748d931cb63fc1230660abdfac1a8f51aabc4a1624374ce898f`,
and launch-contract SHA-256
`863c468c43c47fcc32376702ae53a9e98b273c6c513997e7b567cd31b90cc59c`.
An independent rerun was byte-identical. The [0.90, 1.10] prelaunch balance
gate applies to conditional expected exposure behind the frozen G/T gates, and
all three seed blocks pass it without seed retuning. Version 2 also replays the
final deterministic sample-slot coins. Seed 20260805 has realized G/T ratios
0.8937 for \(H\) and 0.8958 for \(H>0\), just outside that descriptive margin;
the other two blocks are inside. Pooled across the locked Latin square, the
realized ratios are 2220/2209 = 1.00498 for \(H\) and 1768/1761 = 1.00398 for
\(H>0\). These realized draws are reported mechanism diagnostics, not a basis
for changing seeds, rates, or inclusion.

## Hypotheses and decisions

**H1: burstiness without predictability.** G and I have equal candidate
marginals, but G activates fewer groups with larger within-group reward bursts.
A G-I difference with no T-G difference supports a clustering/optimizer effect,
not persistent susceptibility.

**H2: predictable susceptibility.** In the idealized effective-cost model from
the main research report, G changes A's log-odds drift near `p=c`, whereas T
changes the selected template near `p=c/3`. The configured GRPO does not supply
a known constant \(c\); estimate an effective cost from clean or near-clean
log-odds drift and treat the threefold boundary as a follow-up prediction, not
an assumption of this screen. A reproducible T-G selected-template interaction
in A prevalence, accompanied by the predicted strict change, is evidence that
task-correlated verifier susceptibility is learnable.

**H3: recipient attribution remains unresolved.** T-G keeps behavior recipients
fixed at B, so it identifies persistent susceptibility on top of behavior
alignment. It does not identify whether a T effect requires rewarding A itself.
Only after a T-G signal may a T-M arm be added; T-M must preserve the exact
gate, prompt, H, and reward histogram while minimizing A recipients.

Three seeds permit only an exploratory reproducibility screen. Report every
seed, mean, standard deviation, range, and paired prompt-bootstrap measurement
bands. The two-sided exact sign-flip p-value floor is 0.25. A downstream effect
advances only if it exceeds 2 absolute points on OP21--40 or 1 point on
OP41--45 after floor escape, all three seed contrasts share a sign, and the
mechanism audit passes.

Do not call a Stage-1b result a phase transition. If T separates from G, use
the early selected-template log-odds drift only to motivate a fresh design;
the current configuration has no known constant behavior cost. A confirmatory
boundary claim requires an explicit shared cost, multiple gate probabilities,
at least nine fresh balanced seed blocks, both clocks, measured cross-template
gradient transfer, longer plateaus, and no endpoint selection. An approximately
threefold threshold ratio is insufficient because smooth finite-time logistic
amplification produces it too. Test convergence to independently known
boundary intercepts and same-dose history dependence; continued drift toward
zero or collapse against `p*t` supports finite-time amplification instead.

## Integrity and launch gates

Before outcome analysis:

1. all six overlays resolve from the pinned base/common/arm composition;
2. G/T use full `L=128`, behavior recipients, sample-slot coins, p=1/400,
   alpha=1/3, and q=3/400;
3. the three T runs select each declared template exactly once;
4. group gates use only the domain-separated sample-ID hash and are not
   backfilled or seed-retuned;
5. rollout and attempt replay is exact with no metric mismatch;
6. every evaluation is strict, defect-free, and a saved single policy;
7. source, configs, dataset, model, tokenizer, and artifacts are hash-bound.

No GPU submission is allowed until the source snapshot is sealed and the
shared resource gate permits the study without displacing the queued
fixed-clock SFT screen.
