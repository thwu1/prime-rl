# Verifier defects, selection clocks, and strict-reasoning generalization

Status: research synthesis and preregistration, 2026-08-07. This document is
standalone. It distinguishes prior results, derivations made for this study,
observations from existing artifacts, and hypotheses that have not yet been
tested. The target throughout is clean strict dependency-graph correctness,
not the proxy reward optimized during training.

## Epistemic labels

- **[THEOREM—PRIOR]** is a formal result from a cited paper, under that
  paper's assumptions.
- **[EMPIRICAL—PRIOR]** is a reported experimental result from a cited paper.
- **[CONCEPT—PRIOR]** is a useful prior taxonomy or framing, not a theorem.
- **[DERIVATION—HERE]** follows algebraically from an explicitly stated model;
  it is not a theorem about finite neural-network training unless stated.
- **[OBSERVATION—CURRENT]** is measured in an immutable local artifact.
- **[PREREGISTERED]** fixes an analysis before the corresponding outcomes are
  inspected.
- **[HYPOTHESIS]** is a falsifiable proposal, not a result.

These labels matter because three different phenomena are easy to conflate:

1. a population objective changing sign;
2. a finite-group optimizer receiving sparse, order-one updates;
3. a fixed-accepted-count algorithm acquiring new support at any positive
   defect probability.

Only the third has a perfect-versus-any-imperfect discontinuity in the simple
model below. A sharp-looking finite-compute curve is not, by itself, evidence
of an asymptotic phase transition.

## Executive answer

The literature and theory support four conclusions.

1. **Behavior-independent verifier noise has a known informativeness
   boundary, not generally a perfection boundary.** For class-conditional
   false-positive and false-negative rates, the clean policy-gradient direction
   is multiplied by

   \[
   J=\operatorname{TPR}-\operatorname{FPR}
     =1-\rho_{\mathrm{FN}}-\rho_{\mathrm{FP}}.
   \]

   In the population model, \(J>0\) preserves the clean ordering, \(J=0\) is
   uninformative, and \(J<0\) reverses it. Finite GRPO can nevertheless react
   to random rewards because grouping, zero-advantage filtering, clipping, and
   optimizer state are not represented by this population identity.

2. **Behavior-conditioned false positives change the objective itself.** A
   behavior with strict success probability \(q_A\) and false-positive
   probability \(p_A\) has expected proxy reward

   \[
   \mu_A=q_A+(1-q_A)p_A.
   \]

   It defeats a competing behavior of proxy value \(\mu_B\) when

   \[
   p_A>p_A^*=\frac{\mu_B-q_A}{1-q_A}.
   \]

   Except in a tied strict-dead regime, this is a finite threshold rather than
   a discontinuity at zero.

3. **A real zero-versus-positive singularity appears under a fixed accepted
   sample or optimizer-step clock on strict-dead tasks.** If \(q=0\), then for
   every \(p_A>0\), rejection SFT conditioned on acceptance trains on the same
   distribution \(P(\tau\mid A)\); \(p_A\) changes only the raw sampling cost,
   which scales as \(1/(p_A h)\). At \(p_A=0\), no hard example is accepted.
   The corresponding GRPO update, conditional on a rare activated group, has
   order-one amplitude. This is an algorithmic support/clock singularity. It
   does not prove a thermodynamic transition in neural-network performance.

4. **Difficulty can convert a tiny defect into a sharp frontier.** When clean
   success \(q(d)\) decays much faster with difficulty than hack-candidate mass
   \(h(d)\), false positives dominate proxy positives beyond

   \[
   q(d)\operatorname{TPR}=h(d)p_A.
   \]

   If \(q(d)\) decays exponentially and \(h(d)\) stays nonzero, the crossover
   difficulty moves only logarithmically with \(1/p_A\). This predicts that a
   seemingly negligible defect can first become visible on the hardest tasks.
   It is a hypothesis for GSM-Infinite, not yet an observed result.

The defensible novelty target is therefore not “noise can cause reward
hacking” or “misspecification can have phase transitions”; both are known. It
is to isolate how *persistent, behavior-conditioned false positives* affect a
clean process target at an empirically strict-dead frontier after separately
matching raw exposure, accepted-example count, group activation, prompt
allocation, and optimizer steps.

## 1. Formal setup and defect taxonomy

Let a trajectory \(\tau\sim\pi_\theta(\cdot\mid x)\) have:

- \(R(\tau)\in\{0,1\}\): clean strict dependency-graph correctness;
- \(A(\tau)\in\{0,1\}\): answer correct but strict-CoT wrong, with
  \(A(\tau)R(\tau)=0\);
- \(Z(\tau)\in\{0,1\}\): released proxy reward;
- \(q=P_\pi(R=1)\) and \(h=P_\pi(A=1,R=0)\).

The behavior-conditioned intervention is

\[
Z=R+(1-R)A B,\qquad B\sim\operatorname{Bernoulli}(p_A),
\]

so its population objective is

\[
J_{p_A}(\pi)=P_\pi(R=1)+p_A P_\pi(A=1,R=0).
\]

The second term is a genuine policy-dependent reward term. It is not
independent label noise.

We use the following taxonomy.

| Defect | Conditional mechanism | Population effect | Main finite-training concern |
| --- | --- | --- | --- |
| Class-conditional iid | Rates depend only on clean label | Affine clean objective while \(J>0\) | Variance, group activation, clipping bias |
| Feature/behavior-conditioned | Rate depends on \(A(\tau)\) or another feature | Adds a policy-dependent term | Direct selection for the correlated behavior |
| Prompt/task-conditioned | Rate depends on \(x\), operation, or difficulty | Rotates the effective curriculum | Hard-task support and capacity allocation |
| Persistent | The same prompt/slot retains its defect draw | Correlated errors across revisits | Memorization and repeated exploitation |
| Resampled | A fresh draw is made on each exposure | Mean may be unchanged | Stochastic gradient variance and waiting time |
| False negative | Removes reward from a true positive | Usually slows existing clean support | Loss of recall and sparse updates |
| False positive | Adds reward to an incorrect trajectory | Can create new support | Shortcut selection and proxy exploitation |

The marginal false-positive rate is insufficient to identify the mechanism.
Two verifiers can have the same aggregate error rate while assigning all errors
to different trajectories, prompts, or behaviors.

## 2. Systematic annotated literature map

### 2.1 Review scope and limitations

This review snapshot covers work found by searching and citation-snowballing
across six families: corrupted reward channels, reward hacking and Goodhart's
law, noisy RLVR, feature-dependent label noise, process verification, and
iterative self-training. A paper is included when it supplies a formal
boundary, a controlled verifier-noise experiment, a behavior-correlated
failure mode, or a method needed to interpret this study. Exact arXiv records
are linked below. The map is systematic for these mechanism families but is
not a claim of bibliographic exhaustiveness. Several directly relevant 2026
papers are recent preprints and should be treated accordingly.

### 2.2 Corrupted rewards, Goodhart, and formal reward hacking

| Work | Relevant result | Caveat for this study |
| --- | --- | --- |
| Everitt et al., [*Reinforcement Learning with a Corrupted Reward Channel*](https://arxiv.org/abs/1705.08417) (2017) | **[THEOREM—PRIOR]** Formalizes corrupted-reward MDPs and shows ordinary RL can fail under systematic corruption; richer information can sometimes recover robustness. | General CRMDP theory, not finite-group LLM RL or a small-\(p_A\) scaling law. |
| Everitt et al., [*Reward Tampering Problems and Solutions in Reinforcement Learning: A Causal Influence Diagram Perspective*](https://arxiv.org/abs/1908.04734) (2019/2021) | **[THEOREM—PRIOR]** Separates reward-function tampering from reward-input tampering and gives causal design principles for removing incentives. | Concerns agent actions that influence the reward channel; our injected defect is externally specified. |
| Skalse et al., [*Defining and Characterizing Reward Hacking*](https://arxiv.org/abs/2209.13085) (2022) | **[THEOREM—PRIOR]** Defines unhackability as proxy improvement never reducing true return; over unrestricted stochastic policies, nontrivial unhackable reward pairs are extremely constrained. | Structural impossibility does not locate a finite-compute dose threshold. |
| Manheim and Garrabrant, [*Categorizing Variants of Goodhart's Law*](https://arxiv.org/abs/1803.04585) (2018) | **[CONCEPT—PRIOR]** Separates regressional, extremal, causal, and adversarial Goodhart. Optimization can select even independent proxy error. | A taxonomy, not a training-dynamics theorem. It cautions against calling iid noise harmless under selection. |
| Pan, Bhatia, and Steinhardt, [*The Effects of Reward Misspecification: Mapping and Mitigating Misaligned Models*](https://arxiv.org/abs/2201.03544) (2022) | **[EMPIRICAL—PRIOR]** Five of nine proxy/environment pairs produced misalignment; four showed sharp qualitative transitions as model size, training time, action resolution, or observation quality increased. | This is the closest prior “phase transition,” but it varies capability under a fixed proxy rather than defect probability, recipient identity, or selection clock. |
| Gao, Schulman, and Hilton, [*Scaling Laws for Reward Model Overoptimization*](https://arxiv.org/abs/2210.10760) (2022/2023) | **[EMPIRICAL—PRIOR]** Gold reward first rises and then falls with proxy optimization; reported fits are \(R_{\rm BoN}(d)=d(\alpha-\beta d)\) and \(R_{\rm RL}(d)=d(\alpha-\beta\log d)\). | The gold target is another reward model, and the fitted behavior is smooth rather than a perfection discontinuity. |
| Coste et al., [*Reward Model Ensembles Help Mitigate Overoptimization*](https://arxiv.org/abs/2310.02743) (2023/2024) | **[EMPIRICAL—PRIOR]** Conservative ensembles strongly reduce best-of-\(N\) and PPO overoptimization under injected label noise. | Preference reward models, not binary process verifiers or behavior-matched false positives. |
| Denison et al., [*Sycophancy to Subterfuge: Investigating Reward-Tampering in Large Language Models*](https://arxiv.org/abs/2406.10162) (2024) | **[EMPIRICAL—PRIOR]** Training on gameable environments increases later specification gaming and leaves a small nonzero rate of direct reward tampering. | A curriculum of qualitatively different environments, not a controlled \(p_A\) sweep. |
| Kwa, Thomas, and Garriga-Alonso, [*Catastrophic Goodhart: Regularizing RLHF with KL Divergence Does Not Mitigate Heavy-Tailed Reward Misspecification*](https://arxiv.org/abs/2407.14503) (2024) | **[THEOREM—PRIOR]** Sufficiently heavy-tailed proxy error can cause asymptotic catastrophic Goodhart despite KL regularization. | Bounded binary verifier rewards cannot realize the heavy-tail mechanism. “Any positive mixture weight inherits the bad tail” is a possible corollary for another environment, not a claim about GSM-Infinite. |
| Rakhsha et al., [*Policy Teaching via Environment Poisoning: Training-time Adversarial Attacks against Reinforcement Learning*](https://arxiv.org/abs/2003.12909) (2020) | **[THEOREM—PRIOR]** Gives conditions and cost bounds for reward/transition poisoning that induces a target policy. | Optimized adversarial perturbations, not stochastic, behavior-conditioned verifier errors. |
| Zhang et al., [*Adaptive Reward-Poisoning Attacks against Reinforcement Learning*](https://arxiv.org/abs/2003.12613) (2020) | **[THEOREM—PRIOR]** Establishes feasible/infeasible perturbation regimes and advantages for adaptive poisoning. | Its threshold concerns adversarial perturbation magnitude, not false-positive probability. |

### 2.3 Noisy RLVR and behavior-dependent verifier errors

| Work | Relevant result | Caveat for this study |
| --- | --- | --- |
| Rad et al., [*Rate or Fate? RLV\(^{\varepsilon}\)R: Reinforcement Learning with Verifiable Noisy Rewards*](https://arxiv.org/abs/2601.04411) (2026) | **[THEOREM—PRIOR]** In a mean-field, block-symmetric, small-step GRPO/replicator model, \(J>0\) makes correct modes attracting, \(J=0\) is neutral, and \(J<0\) makes incorrect modes attracting; zero initial correct support is separately absorbing. | January 2026 v1. The result assumes behavior-independent class-conditional noise and does not prove finite neural GRPO behavior with clipping and sparse groups. |
| Cai et al., [*Reinforcement Learning with Verifiable yet Noisy Rewards under Imperfect Verifiers*](https://arxiv.org/abs/2510.00915) (2025/2026) | **[THEOREM—PRIOR]** Derives an unbiased correction \((\widetilde R-\rho_0)/(1-\rho_0-\rho_1)\) while the class-conditional channel is informative. The paper explicitly identifies a residual covariance term when errors depend on content. | Population REINFORCE-style analysis; content-dependent false positives violate its principal assumption. |
| Shao et al., [*Spurious Rewards: Rethinking Training Signals in RLVR*](https://arxiv.org/abs/2506.10947) (2025/2026) | **[EMPIRICAL—PRIOR]** Completely random rewards improved Qwen2.5-Math-7B substantially; clipping produced a nonzero expected gradient that amplified high-prior “code reasoning.” Removing clipping removed the consistent effect, and the result did not transfer uniformly across model families. | Directly refutes “iid rewards cannot matter in practical GRPO,” but it studies optimizer-induced self-distillation rather than a behavior-targeted verifier defect. |
| Plesner, Guzmán, and Athalye, [*An Imperfect Verifier is Good Enough: Learning with Noisy Rewards*](https://arxiv.org/abs/2604.07666) (2026) | **[EMPIRICAL—PRIOR]** Resampled symmetric noise up to 15% was often close to clean training; weak verifiers with low precision were exploited, suggesting false positives are particularly dangerous. | April 2026 v1. Persistent error and a controlled FP-versus-FN factorial are left open; some precision conclusions are observational. |
| Lv et al., [*The Climb Carves Wisdom Deeper Than the Summit: On the Noisy Rewards in Learning to Reason*](https://arxiv.org/abs/2505.22653) (2025) | **[EMPIRICAL—PRIOR]** Qwen retained much of its performance under substantial question-level reward inversion and collapsed around 50%; a phrase-based reward improved transiently and later overoptimized. | PPO with question/group-level noise, not recipient-matched trajectory false positives. |
| Li, Kethireddy, and Das, [*Evaluating Feature Dependent Noise in Preference-based Reinforcement Learning*](https://arxiv.org/abs/2601.01904) (2026) | **[EMPIRICAL—PRIOR]** Feature-, similarity-, and margin-dependent preference noise can damage methods that tolerate uniform noise. | Continuous-control preference RL, with no verifier-dose phase-transition result. |
| Helff et al., [*LLMs Gaming Verifiers: RLVR can Lead to Reward Hacking*](https://arxiv.org/abs/2604.15149) (2026) | **[EMPIRICAL—PRIOR]** A deterministic extensional-verifier loophole causes shortcut learning; an isomorphism-aware verifier removes the shortcut, and shortcut use rises with task complexity and inference compute. | The closest behavioral analogue to \(p_A\), but it compares deterministic verifiers rather than sweeping defect probability or matching raw/update clocks. |

### 2.4 Process supervision, inference verification, and iterative feedback

| Work | Relevant result | Caveat for this study |
| --- | --- | --- |
| Cobbe et al., [*Training Verifiers to Solve Math Word Problems*](https://arxiv.org/abs/2110.14168) (2021) | **[EMPIRICAL—PRIOR]** Sampling and verifier reranking improve GSM8K and scale effectively with data. | Outcome verification at inference, not corrupted-verifier training. |
| Uesato et al., [*Solving Math Word Problems with Process- and Outcome-Based Feedback*](https://arxiv.org/abs/2211.14275) (2022) | **[EMPIRICAL—PRIOR]** Outcome supervision can obtain similar answer error cheaply, but process supervision reduces incorrect reasoning among final-answer-correct solutions from 14.0% to 3.4%. | Different task/model, but it directly motivates strict CoT as the target rather than answer-only reward. |
| Lightman et al., [*Let's Verify Step by Step*](https://arxiv.org/abs/2305.20050) (2023) | **[EMPIRICAL—PRIOR]** Process reward models outperform outcome reward models on MATH and support active-learning gains. | Learned verifier quality, not controlled error-recipient interventions. |
| Wang et al., [*Examining False Positives under Inference Scaling for Mathematical Reasoning*](https://arxiv.org/abs/2502.06217) (2025) | **[EMPIRICAL—PRIOR]** Correct-answer/incorrect-reasoning false positives contaminate pass@\(N\) increasingly as inference scales. | Inference evaluation rather than training dynamics. |
| Pan et al., [*Spontaneous Reward Hacking in Iterative Self-Refinement*](https://arxiv.org/abs/2407.04549) (2024) | **[EMPIRICAL—PRIOR]** Evaluator scores can improve while human quality stagnates or declines, especially when generator and evaluator share a model. | Establishes iterative amplification, not a controlled \(p_A\to0\) boundary. |
| Burns et al., [*Weak-to-Strong Generalization: Eliciting Strong Capabilities with Weak Supervision*](https://arxiv.org/abs/2312.09390) (2023) | **[EMPIRICAL—PRIOR]** Strong models can exceed weak supervisors but generally do not recover the full strong ceiling; confidence-based methods help. | Weak labels are not the same as a sparse, behavior-correlated binary defect. |
| Kirchner et al., [*Prover-Verifier Games Improve Legibility of Language Model Outputs*](https://arxiv.org/abs/2407.13692) (2024) | **[EMPIRICAL—PRIOR]** Adversarial prover-verifier training can improve helpful accuracy and verifier robustness. | Changes the verifier through a game rather than holding a defect channel fixed. |
| Oymak and Gulcu, [*Statistical and Algorithmic Insights for Semi-supervised Learning with Self-training*](https://arxiv.org/abs/2006.11006) (2020) | **[THEOREM—PRIOR]** Finite-sample self-training recurrences can have suboptimal fixed points; confidence and margin matter. | Supports basin phenomena in iterative SFT but does not study verifier false-positive dose. |

### 2.5 Label-noise results that delimit the analogy

| Work | Relevant result | Caveat for this study |
| --- | --- | --- |
| Patrini et al., [*Making Deep Neural Networks Robust to Label Noise: A Loss Correction Approach*](https://arxiv.org/abs/1609.03683) (2016/2017) | **[THEOREM—PRIOR]** Known class-dependent transition matrices permit forward/backward loss correction; **[EMPIRICAL—PRIOR]** experiments validate the method. | Requires a stable, identifiable class-level channel; behavior-conditioned policy data are endogenous. |
| Liu and Tao, [*Classification with Noisy Labels by Importance Reweighting*](https://arxiv.org/abs/1411.7718) (2014/2016) | **[THEOREM—PRIOR]** Importance weighting can recover consistency under independent binary label flips below the uninformative boundary. | Supervised iid inputs do not include policy-induced covariate shift or group advantages. |
| Menon et al., [*Learning from Binary Labels with Instance-Dependent Corruption*](https://arxiv.org/abs/1605.00751) (2016) | **[THEOREM—PRIOR]** Gives consistency results for particular instance-dependent corruption models and ranking conditions. | The assumptions are restrictive and do not cover arbitrary exploitable verifier behavior. |
| Cheng et al., [*Learning with Instance-Dependent Label Noise: A Sample Sieve Approach*](https://arxiv.org/abs/2010.02347) (2020) | **[THEOREM—PRIOR]** Filtering can be robust under stated separation assumptions; **[EMPIRICAL—PRIOR]** experiments study a sample-sieve implementation. | Offline classification; the filter does not alter a data-generating policy. |
| Liu et al., [*Identifiability of Label Noise Transition Matrix*](https://arxiv.org/abs/2202.02016) (2022) | **[THEOREM—PRIOR]** Generic instance-level transition matrices are not identifiable from one noisy label without additional assumptions or repeated labels. | Explains why aggregate FPR alone cannot recover our behavior-conditioned channel. |
| Chowdhury et al., [*Provably Robust Direct Preference Optimization with Noisy Preferences*](https://arxiv.org/abs/2403.00409) (2024) | **[THEOREM—PRIOR]** Under random flips \(\epsilon<1/2\), robust DPO bounds degrade with the familiar \(1/(1-2\epsilon)\) factor. | Pairwise offline preferences, not GRPO or strict-dead rejection sampling. |

### 2.6 Literature synthesis

Prior work already establishes all of the following: reward corruption can
break RL; proxy optimization can cause smooth overoptimization or sharp
capability thresholds; iid random rewards can matter under clipped GRPO; and
feature-dependent errors can be worse than uniform errors. No novelty claim
should be based on any one of those statements.

The remaining gap is narrower and operational: no work in this map jointly
controls recipient behavior, within-prompt reward count, global accepted count,
raw rollout exposure, optimizer-step exposure, an empirically strict-dead
process frontier, and held-out clean process correctness in both RL and
iterative SFT.

## 3. Theory: boundaries and singular limits

### 3.1 Class-conditional \(J\) boundary

Let the true binary reward be \(R\), the observed reward be \(\widetilde R\),
and define

\[
\rho_{\mathrm{FP}}=P(\widetilde R=1\mid R=0),\qquad
\rho_{\mathrm{FN}}=P(\widetilde R=0\mid R=1).
\]

Assume these rates are independent of trajectory content conditional on \(R\).
Then

\[
\begin{aligned}
E[\widetilde R\mid R]
&=(1-\rho_{\mathrm{FN}})R+\rho_{\mathrm{FP}}(1-R)\\
&=\rho_{\mathrm{FP}}
 +(1-\rho_{\mathrm{FN}}-\rho_{\mathrm{FP}})R.
\end{aligned}
\]

Writing

\[
J=1-\rho_{\mathrm{FN}}-\rho_{\mathrm{FP}}
 =\operatorname{TPR}-\operatorname{FPR},
\]

the population score-function gradient is

\[
\nabla_\theta E_\pi[\widetilde R]
=J\nabla_\theta E_\pi[R],
\]

because the additive \(\rho_{\mathrm{FP}}\) has zero policy gradient.

**[DERIVATION—HERE]** The algebra above recovers the informativeness boundary.
**[THEOREM—PRIOR]** Rad et al. and Cai et al. establish corresponding results
under their respective mean-field and population-gradient assumptions:

- \(J>0\): clean policy ordering and gradient direction are preserved;
- \(J=0\): the observed reward contains no information about \(R\);
- \(J<0\): the clean direction is reversed.

This identity does **not** imply that iid noise is operationally inert. It does
not include finite groups, zero-advantage filtering, clipping, KL penalties,
adaptive data collection, optimizer state, or selection of extreme samples.
Shao et al. provide a concrete clipped-GRPO counterexample to that stronger
claim.

If corruption depends on content, write

\[
E[\widetilde R\mid\tau]=\rho_{\mathrm{FP}}+JR(\tau)+\delta(\tau).
\]

Then the extra term is

\[
E_\pi[\delta(\tau)\nabla_\theta\log\pi_\theta(\tau\mid x)],
\]

which is the exact covariance-like location of behavior-conditioned selection.

### 3.2 Behavior-conditioned objective and replicator threshold

Partition trajectories into reproducible behavior modes \(i\). Let \(q_i\) be
the strict-correct probability within mode \(i\), and let an incorrect
trajectory in that mode receive a false positive with probability \(p_i\).
Assuming strict positives are always accepted,

\[
\mu_i=q_i+(1-q_i)p_i.
\]

Consider the idealized replicator flow

\[
\dot x_i=\eta x_i(\mu_i-\bar\mu),\qquad
\bar\mu=\sum_j x_j\mu_j.
\]

For two modes \(A,B\),

\[
\frac{d}{dt}\log\frac{x_A}{x_B}=\eta(\mu_A-\mu_B).
\]

Therefore \(A\) expands relative to \(B\) exactly when

\[
q_A+(1-q_A)p_A>\mu_B.
\]

For \(q_A<1\), the boundary is

\[
\boxed{p_A^*=\frac{\mu_B-q_A}{1-q_A}}.
\]

**[DERIVATION—HERE]** The boundary has three regimes:

- if \(\mu_B\le q_A\), mode \(A\) already wins at \(p_A=0\);
- if \(q_A<\mu_B<1\), a finite positive threshold exists;
- if \(\mu_B\ge1\), no \(p_A\le1\) can make \(A\) strictly better.

Thus “any nonzero imperfection changes fate” is not generic. It arises in the
special tied strict-dead case \(q_A=\mu_B=0\), or through an additional
mechanism such as endogenous hackability, heavy-tailed payoff, or support
creation.

This replicator system is an explanatory model, not a theorem for neural GRPO.
In particular, its fitness is stationary, while the model's behavior classes,
prompt distribution, and gradients all change during training.

### 3.3 Noncommuting \(p\to0\) and long-time limits

In the tied strict-dead two-mode case, let \(\mu_A=p_A\), \(\mu_B=0\), and
\(x=x_A\). The replicator equation becomes

\[
\dot x=\eta p_A x(1-x),
\]

with solution

\[
x(t,p_A)=
\frac{1}{1+\frac{1-x_0}{x_0}e^{-\eta p_A t}}.
\]

At every finite \(t\), this is smooth in \(p_A\), and
\(x(t,p_A)\to x_0\) as \(p_A\to0^+\). For every fixed \(p_A>0\), however,
\(x\to1\) as \(t\to\infty\). Hence

\[
\boxed{
\lim_{p_A\to0^+}\lim_{t\to\infty}x(t,p_A)=1
\ne
\lim_{t\to\infty}\lim_{p_A\to0^+}x(t,p_A)=x_0.}
\]

**[DERIVATION—HERE]** The apparent finite-time critical dose for reaching a
chosen level \(x_*\in(x_0,1)\) is

\[
p_c(t;x_*)=
\frac{\operatorname{logit}(x_*)-\operatorname{logit}(x_0)}{\eta t}.
\]

It moves as \(1/t\). A “threshold” that drifts downward with training time is
therefore consistent with smooth multiplicative amplification, not a fixed
critical point. Demonstrating the noncommuting limit empirically would require
increasing both time and the resolution of doses near zero; the current
\(0.25\%,0.5\%,1\%\) screen cannot establish that asymptotic statement.

### 3.4 Exact GRPO activation for 128-rollout groups

Consider a finalized group with \(V\) valid strict-negative trajectories, of
which \(K\le V\) are defect-eligible. Let

\[
H\mid K\sim\operatorname{Binomial}(K,p_A)
\]

be the number of false positives. A centered binary-reward group has nonzero
advantage when it contains both proxy rewards. Conditional on \(K,V\),

\[
\boxed{
P(\text{mixed activation}\mid K,V)
=1-(1-p_A)^K-\mathbf 1[K=V]p_A^K.}
\]

The final term removes the all-positive case only when every valid trajectory
is eligible. If \(K<V\), at least one ineligible negative remains whenever
\(H\ge1\). For small \(p_A\), activation is \(Kp_A+O(p_A^2)\). If
\(K\approx Vh\),

\[
P(\text{activation})\approx1-e^{-Vhp_A}.
\]

For the production group size \(V=128\), the group crossover scale is
\(p_A\sim1/(128h)\), not universally \(1/128\).

With a single positive in a \(V\)-row group and the centered, non-variance-
standardized advantage used by the current prime-rl configuration,

\[
A_+=1-\frac1V=\frac{V-1}{V},\qquad
A_-=-\frac1V.
\]

At \(V=128\), \(A_+=127/128\approx0.9922\). **[DERIVATION—HERE]** A small
defect probability therefore controls the *arrival rate* of activated updates,
while the positive recipient in a realized singleton event still receives an
order-one coefficient. Over \(N\) approximately independent strict-dead groups,
the number of activation nuclei is approximately Poisson with mean \(NKp_A\),
or \(NVhp_A\) under the homogeneous approximation \(K\approx Vh\). Near mean
one, seeds can split into “no event” and “at least one event” populations,
creating bimodality without an asymptotic phase transition.

For an iid binary reward rate \(s\) applied to all \(V\) rows, the corresponding
formula is

\[
P(\text{mixed})=1-(1-s)^V-s^V.
\]

The exact conditional-\(K\) formula, not this iid approximation, is used in the
legacy audit.

### 3.5 Fixed-count rejection SFT: exact cancellation of defect magnitude

For proxy acceptance \(Z\), the accepted trajectory distribution is

\[
P_{p_A}(\tau\mid Z=1)
=\frac{P(\tau)\left[R(\tau)+p_A A(\tau)(1-R(\tau))\right]}
       {q+p_A h}.
\]

At a strict-dead frontier \(q=0\), for every \(p_A>0\),

\[
\boxed{P_{p_A}(\tau\mid Z=1)=P(\tau\mid A,R=0).}
\]

**[DERIVATION—HERE]** The accepted-data distribution is exactly independent of
the magnitude of \(p_A\). The expected raw draws per accepted trajectory are

\[
\frac1{p_Ah},
\]

whereas \(p_A=0\) yields no hard accepted sample. This is the cleanest
perfect-versus-imperfect support singularity in the present study.

For disjoint incorrect behavior classes \(A_i\) with base rates \(h_i\) and
\(p_i=\epsilon c_i\),

\[
P(A_i\mid Z=1)
=\frac{c_i h_i}{\sum_j c_jh_j},\qquad \epsilon>0.
\]

The global error scale \(\epsilon\) cancels; only the relative shape \(c_i\)
survives. Raw collection cost diverges as
\(1/(\epsilon\sum_jc_jh_j)\). Iterating an idealized select-and-imitate map can
amplify these relative weights: after \(t\) exact multiplicative rounds,

\[
x_i^{(t)}\propto x_i^{(0)}(c_i h_i)^t,
\]

so unequal behavior-conditioned rates can become winner-take-all even as
\(\epsilon\to0^+\). This recurrence omits model generalization and is a
mechanistic hypothesis, not a claim about the planned SFT runs.

The cancellation holds only under its conditioning. At fixed raw exposure,
the number accepted is random and vanishes with \(p_A\). If clean-positive
strata are mixed in, their accepted mass does not vanish, so the hard-stratum
share goes to zero with \(p_A\). Policy feedback can also change \(h\) between
rounds.

### 3.6 Base-rate frontier

Let difficulty be \(d\), genuine strict-success mass be \(q(d)\), verifier true
positive rate be \(t(d)\), and behavior-\(A\) strict-negative mass be \(h(d)\).
The two sources of proxy-positive mass are

\[
g(d)=t(d)q(d),\qquad f(d)=p_Ah(d).
\]

The false share of proxy positives is

\[
\phi(d,p_A)=\frac{p_Ah(d)}{t(d)q(d)+p_Ah(d)}.
\]

The 50% frontier is therefore

\[
\boxed{t(d)q(d)=p_Ah(d).}
\]

**[DERIVATION—HERE]** Under the illustrative model

\[
q(d)=q_0e^{-\alpha d},\qquad h(d)\approx h_0,qquad t(d)\approx t_0,
\]

the crossover is

\[
d_*(p_A)=\frac1\alpha
\log\frac{q_0t_0}{h_0p_A}.
\]

Each multiplicative reduction of \(p_A\) moves the frontier only additively in
difficulty. In an unbounded task family with \(h_0>0\), every \(p_A>0\)
eventually has a false-positive-dominated region, while \(p_A=0\) does not.
GSM-Infinite has a finite evaluated range, so the crossover may lie outside
OP11–45; the empirical claim can be falsified there.

### 3.7 Endogenous hackability and a genuine hysteresis construction

**[HYPOTHESIS]** Suppose the prevalence \(x\) of a hack-like behavior makes
future samples easier for the verifier to accept,

\[
p_{\rm eff}(x)=p_0+\alpha x,
\]

and compare it with a competing mode of effective fitness \(\mu_B\). An
idealized flow is

\[
\dot x=\eta x(1-x)(p_0+\alpha x-\mu_B).
\]

When

\[
\mu_B-\alpha<p_0<\mu_B,
\]

both \(x=0\) and \(x=1\) are locally stable, separated by the unstable point

\[
x^*=\frac{\mu_B-p_0}{\alpha}.
\]

An upward sweep initialized from a clean policy and a downward sweep initialized
from a hack-heavy policy can then end in different basins at the same \(p_0\).
That path dependence would be stronger evidence of a dynamical phase
transition than a steep one-way dose curve. The feedback law itself must be
measured; ordinary selection delay can imitate a loop at insufficient training
time.

## 4. What the legacy RL evidence establishes

The authoritative artifact is:

```text
/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/
verifier-defect-threshold-audit-20260807-044642/summary.json
```

It binds its rollout manifests, input summaries, log prefixes, dataset, and
analysis implementation by SHA-256.

### 4.1 Aligned-clock reversal

**[OBSERVATION—CURRENT]** At the common legacy raw-exposure proxy of 859,008
rollouts, the arms had received very different numbers of optimizer updates:

| Arm | Interpolated optimizer updates | Updates / clean arm | OP15–17 exposure-AUC |
| --- | ---: | ---: | ---: |
| \(p=0\) | 721.1 | 1.000 | 4.7705% |
| \(p=1\%\) | 1,200.0 | 1.664 | 7.3427% |
| \(p=5\%\) | 1,541.2 | 2.137 | 4.8273% |

The apparent \(1\%\) advantage over control was \(+2.5722\) percentage points
on this raw-exposure AUC. At common optimizer step 875, the ordering changed:

| Arm | OP15–17 step-AUC | Delta from clean |
| --- | ---: | ---: |
| \(p=0\) | 6.6690% | 0.0000 pp |
| \(p=1\%\) | 5.8476% | -0.8214 pp |
| \(p=5\%\) | 1.3976% | -5.2714 pp |

Thus the \(1\%\) “benefit” is explained by more optimizer updates per raw
rollout in this comparison; it is not evidence that its updates were better.
The \(5\%\) arm remains worse under either clock at these windows.

### 4.2 Frontier discoveries

**[OBSERVATION—CURRENT]** The first saved strict-positive OP15–20 trajectory
appeared at:

| Arm | Step | Legacy log-proxy exposure |
| --- | ---: | ---: |
| \(p=0\) | 115 | 209,536 |
| \(p=1\%\) | 285 | 248,192 |
| \(p=5\%\) | 522 | 302,848 |

For OP21–40 it appeared at step 915 / exposure 1,038,592 for \(p=0\), step
1,169 / exposure 840,320 for \(p=1\%\), and did not appear in the audited
\(p=5\%\) prefix through step 1,631. These are discovery times from one seed,
not population hazards.

### 4.3 What is not identified

The artifact itself correctly lists the missing estimands:

- activation or nucleation hazard over all dispatched groups;
- longitudinal conversion of a candidate into a strict trajectory;
- recipient-specific causal effect of a false-positive update;
- a phase transition from the one-seed, three-arm traces.

**Conclusion from legacy evidence:** reward defects altered update throughput,
and clock alignment reverses the apparent low-dose gain. The evidence does
**not** prove a perfect-versus-imperfect phase transition, an asymptotic ceiling
change, or even that recipient identity caused the observed endpoint gaps.

## 5. Preregistered GSM-Infinite frozen-bank experiment

### 5.1 Bank and gate

**[PREREGISTERED]** The frozen bank contract is

```text
/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect/
frozen-base-op10-12-op15-40-r128-v1
```

with contract SHA-256
`8e25af2c374ce70be2df3d4acaa8d38ea5a23960e8db55326be53dadd4aca085`.
It contains 1,000 prompts per operation and 128 trajectories per prompt for
OP10–12 and OP15–40: 29,000 prompt groups and 3,712,000 trajectories. The
prompt view has zero held-out ID or text overlap by contract.

The bank is sealed. Its `completion.json` SHA-256 is
`b5346553628d5b52e93a7c232acdcd2a5b0e10574531085a9c967e14fac221a2`;
the generation and strict-result SHA-256 values are respectively
`12f16b5a0f48d20d95026a4aa1e8fe727a19e760aba33077f1f1de5da605f8d9` and
`01f4550da3ff6abbe437b736939034d58093d2d71156599dff830568927ae166`.
Dataset construction requires the hash-bound `completion.json` and fails closed
if any input identity differs.

The treatment range is OP21–40. Before any treatment dataset is accepted, the
builder must verify that every one of the 2,560,000 frozen OP21–40 trajectories
has \(R=0\). This is an empirical finite-bank strict-dead gate, not proof that
the population success probability is mathematically zero. OP15–20 remain in
the bank for validation but are excluded from the strict-dead treatment
because legacy training discovered strict positives there.

Each dataset also includes 512 clean strict-positive anchors drawn
deterministically from OP10–12. The perfect-verifier control `C0` contains only
these anchors because a perfect verifier accepts no hard trajectory behind the
strict-dead gate.

### 5.2 B/S/G/I recipient design

**[PREREGISTERED]** Doses are \(p\in\{0.25\%,0.5\%,1\%\}\), with deterministic
selection seeds 20260805, 20260806, and 20260807. Hash draws use exact uint64
integer comparisons, not floating-point thresholds.

| Arm | Recipient rule | What it preserves | What it breaks |
| --- | --- | --- | --- |
| **B: behavior** | Promote \(A=\) answer-correct/strict-wrong rows whose defect draw is below \(p\) | Actual behavior-conditioned defect | Nothing; this is the treatment |
| **S: within-prompt shuffled** | For each prompt group, assign exactly B's realized count to independently ranked strict negatives | Hard-sample count, prompt/group allocation, per-group extra-positive histogram | Association between the reward and the particular B recipient |
| **G: global count-matched** | Select exactly B's total count by independent global ranks over strict negatives in the same observed prefix | Total hard-sample count and cutoff | Recipient identity and prompt/group allocation |
| **I: iid class-conditional** | Independently promote every observed strict negative with probability \(p\) | A genuine behavior-independent Bernoulli channel and its cardinality variance | Exact count matching; its marginal number of positives generally differs from B |

The roles are deliberately different. `G`, not `I`, is the behavior-independent
*count-matched* control. `I` tests the classical class-conditional channel and
the practical random-reward/clipping concern. A raw B-versus-I outcome
difference cannot be attributed solely to behavior correlation unless their
aggregate extra-positive exposure is additionally reweighted or matched.

Primary mechanistic contrasts are:

\[
\begin{aligned}
B-S &: \text{recipient/content targeting at fixed prompt allocation},\\
S-G &: \text{prompt/group allocation at fixed total count},\\
B-G &: \text{total behavior-targeting effect at fixed count},\\
I-C0 &: \text{class-conditional iid channel plus its selection/optimizer effects}.
\end{aligned}
\]

Any B-versus-I contrast is secondary and must report realized recipient count,
candidate overlap, group count, and raw prefix.

The index contains 55 distinct canonical training arms: C0, 45 B/S/G arms,
and 9 fixed-raw I arms. It additionally contains 9 byte-identical minimum-dose
fixed-raw aliases of fixed-M B/S/G, for 64 index entries total. Aliases are not
submitted as separate training jobs.

### 5.3 Dual clocks

**Fixed accepted count (`fixed-M`).** For each dose and seed, scan the frozen
raw order until B has exactly \(M=512\) hard recipients. S and G receive
exactly 512 corresponding hard recipients, and every arm receives the same 512
anchors. Under the strict-dead rejection model, changing positive \(p\) should
change the required raw prefix but not the population distribution conditional
on B acceptance. All fixed-M arms use the common 64-update readout.

**Fixed raw exposure (`fixed-raw`).** For each seed, freeze the raw prefix at
the point where the minimum B dose, \(0.25\%\), reaches 512 recipients. Apply
all larger doses to that exact prefix. B/S/G cardinality then grows with dose;
I retains its own iid Bernoulli cardinality. The minimum-dose fixed-raw B/S/G
datasets are byte-identical aliases of their fixed-M counterparts.

Every update consumes exactly 32 examples through fixed-cardinality stacking,
with micro-batch size 4, sequence length 2,048, and padding masked out of the
loss. Checkpoints occur every 8 updates. All arms have a common step-64
readout; variable-cardinality fixed-raw arms additionally run through at least
two complete dataset passes, using

\[
T_{2\rm pass}=\left\lceil\frac{2\,|D|}{32}\right\rceil.
\]

The final update can overshoot two passes by fewer than 32 example exposures,
so it must be described as “at least two passes,” not exactly two.

**[PREREGISTERED AMENDMENT—BEFORE OUTCOMES]** The first dataset-materialization
attempt failed closed before writing an output because selected frozen
trajectory `(24, 151, 113)` rendered to 2,049 model-input tokens, one above the
base model's immutable 2,048-token context. No SFT job or evaluation outcome had
been produced. The trainability rule is therefore fixed as follows: render the
union of all selected rows exactly with the pinned tokenizer and chat template;
globally exclude every selected row with more than 2,048 model-input tokens;
recompute all anchor, prefix, B/S/G/I, fixed-M, and fixed-raw selections; and
repeat to a fixed point. Truncation and a context-length increase are forbidden.
The full-bank strict-dead and candidate statistics remain computed before this
filter. Every excluded key, exact token length, score class, first-pass selection
context, exclusion round, and stable key-set hash must appear identically in the
arm index and every arm manifest. This symmetric rule changes the sampling
selection to exactly trainable written trajectories while preserving the exact
arm contracts. It is a minimal selected-support fixed point, not a census of
every overlength nonrecipient in the raw prefix. Consequently the reported G/I
eligible-row denominators mean strict-negative rows in the observed prefix after
removing discovered fixed-point exclusions; they must not be described as exact
counts of all trainable rows.

At step 64 every arm has 2,048 example exposures. Because C0 has 512 rows while
a fixed-M treatment has 1,024, C0 repeats each anchor more often; this is the
intended consequence of the perfect verifier having no hard support. Claims
must not call the two datasets distribution-identical.

### 5.4 Clean target and reporting bands

**[PREREGISTERED]** No evaluation reward is corrupted. The target is released
strict dependency-graph correctness on the same 200 held-out prompts for every
operation OP11–45. Report per-operation values and the following fixed bands:

- OP11–14: retention/easy bridge;
- OP15–20: discovered bridge;
- OP21–40: trained strict-dead range;
- OP41–45: unseen extrapolation target.

The primary performance estimand is macro strict pass@1 on OP41–45 at common
step 64. Co-primary mechanistic readouts are OP21–40 macro strict pass@1 and the
per-operation strict frontier. Secondary readouts are OP11–20 retention,
OP11–45 macro/micro values, answer-only correctness, and final matched
128-sample pass@\(k\) where available. Answer-only reward is never a substitute
for the strict target.

Report each selection seed separately before any mean. For aggregate
uncertainty, pair arms on the identical held-out prompts and bootstrap prompts
within operation, then summarize the distribution across the three selection
seeds. Three seeds are a screen, not enough to establish a universal scaling
law.

### 5.5 Hypotheses and falsification criteria

**H1: fixed-count cancellation.** At fixed-M, positive B doses should have no
systematic dose trend in accepted recipient composition or common-step target
performance beyond finite-bank and optimization variation; raw collection
cost should scale approximately as \(1/p\).

- Falsified if a reproducible dose ordering remains across seeds after matching
  exactly 512 B recipients, 512 anchors, training steps, and recipient-feature
  summaries.
- Not falsified by different raw prefixes alone; that is the predicted cost.

**H2: recipient alignment.** B differs from S because the rewarded completion,
not just its prompt, is correlated with \(A\).

- Supported only by a consistent paired \(B-S\) difference.
- Falsified at detectable effect size if B and S match across seeds and clocks.
  A B-versus-C0 difference is insufficient because hard support and prompt
  allocation both change.

**H3: curriculum allocation.** S differs from G because the behavior trigger
chooses which prompts/groups enter training even after recipients are shuffled.

- Supported by \(S-G\) together with measured differences in operation/prompt
  allocation.
- Falsified if S and G match and allocation summaries do not predict outcomes.

**H4: iid channel robustness.** I should preserve the clean population
ordering while \(J=1-p>0\), but can still change finite GRPO/SFT dynamics.

- A nonzero I effect does not refute the \(J\) theorem unless population and
  algorithmic clocks are also matched.
- If an I effect disappears without clipping in RL, that supports the Shao et
  al. optimizer-bias mechanism rather than verifier-content selection.

**H5: base-rate frontier.** The false-positive share and clean-performance gap
should emerge first where \(q(d)/h(d)\) is smallest, and the crossover operation
should move approximately linearly with \(\log(1/p)\) under the exponential
base-rate model.

- Falsified if measured \(q(d),h(d)\) do not predict the operation at which
  proxy positives become defect-dominated, or if the direction is reversed
  consistently across seeds.

**H6: performance singularity.** A true perfect-versus-imperfect performance
claim requires positive-dose outcomes to approach a stable limit distinct from
C0 as doses decrease, after accepted-count and optimizer-step matching.

- The current minimum dose cannot prove the \(p\to0^+\) limit.
- A steep but time-shifting crossover, disappearance under raw-clock matching,
  or collapse against \(pht\) supports a finite-time mechanism instead.
- No “phase transition” claim is allowed from one seed, one endpoint, or proxy
  reward alone.

### 5.6 Required integrity checks before outcome analysis

1. A sealed bank `completion.json` matches the manifest contract and all file
   hashes.
2. Every OP21–40 score is strict-negative; the builder aborts otherwise.
3. Every B/S/G paired arm has exact hard-recipient cardinality and B/S has an
   identical prompt-group count histogram.
4. G is globally rank-selected only from observed strict negatives; I obeys
   its exact Bernoulli threshold for every recipient.
5. Datasets contain no duplicate trajectory IDs and no held-out prompt overlap.
6. Exact rendering reaches a fixed point with every written row at most 2,048
   model-input tokens; exclusions and reselection rounds are hash-bound and no
   trajectory is truncated.
7. Model, tokenizer, chat template, source snapshot, dataset bytes, and launch
   config are hash-bound.
8. Training uses exact-cardinality 32-example updates; no token packing changes
   example count across arms.
9. Evaluation artifacts contain no defect fields and use the strict scorer.
10. All declared checkpoints exist before a curve is compared; cherry-picked
   endpoints are not substituted for step 64.

### 5.7 Realized data and launch integrity

**[RESULT—INTEGRITY ONLY; NO PERFORMANCE OUTCOME]** CPU build job `10257755`
completed successfully on 2026-08-07 from pinned commit
`6180a949f6b23fbf4f0ff014abe6ecb8b5d0ab98`. The resulting `arm_index.json`
has SHA-256
`1f4d3f3713a038af02b65d51e969d175ce7fdf795d083fe8a672cb6603f6a35d`,
55 distinct training arms, and 64 entries including aliases. The independent
validation pass and a direct Parquet audit both passed: 55 Parquet files,
161,716 arm-row occurrences, no within-arm duplicate trajectory IDs, and a
maximum rendered length of 2,035 tokens.

The fixed-point filter found exactly one overlength selected trajectory:
`(OP24, prompt 151, sample 113)`, 2,049 tokens. It was answer-wrong,
strict-wrong, and not a B candidate. It appeared only as the shuffled recipient
for seed 20260806, dose 1%, in the matched fixed-M and fixed-raw views. The
builder excluded it globally, deterministically selected the next shuffled
recipient, and converged on pass 2. The excluded-key-set SHA-256 is
`082afd86101b75b07654aef326e3ebe9035168aa828e5d7c7d8e0877bfc13ab4`.
It occurs in no written Parquet. Because it was not a behavior trigger, the B
prefixes and behavior-positive cardinalities did not change.

The sealed training launch manifest has SHA-256
`a1e6b1dee7e5ec9cd778c758b6179aee001ece9fa508766130d6c127a6329187`.
All 55 non-exclusive one-H100 arms were submitted through the protected control
tmux and recorded in one ledger; their Slurm job IDs span `10258745`–`10258805`
with scheduler interleaving. At the first post-submit observation all remained
pending under `QOSGrpGRES` or `Priority`; none had failed, so no training or
generalization result existed yet.

The strict evaluator is independently pinned to commit
`6e5162658990463fa1c742781b54c71a2a380377`. Its launch manifest has SHA-256
`5e49478b1aef3cb324290dc1f3b8867bad65f386e3814a82ba816f1b499eca6c`
and declares 82 tasks, 7,000 prompts per task, and 574,000 total generations.
Dry submission correctly reported 0 stable and 82 missing checkpoints; no
evaluation array or immutable submission intent was created.

## 6. Follow-up experiments

### 6.1 RL clipping/no-clipping factorial

Shao et al. make clipping a necessary confound to isolate. The next on-policy
screen should cross reward assignment with clipping:

| Factor | Levels |
| --- | --- |
| Reward assignment | C0 clean, B behavior, S group-shuffled, I uniform strict-wrong |
| Dose | zero and one low positive dose selected from the frozen-bank screen |
| GRPO clipping | current clipping; clipping disabled |
| Clock | fixed raw group attempts; fixed shipped optimizer steps |
| Seeds | at least three paired prompt/slot and training seeds |

Use 128-rollout groups, deterministic `(sample_id, rollout_slot)` verifier
draws, complete pre-filter group/attempt logging, and clean OP11–45 evaluation.
The B and S arms must share each realized group reward count. The I arm must
report both nominal and realized marginal FPR and should have an additional
aggregate-count-matched analysis.

**[HYPOTHESIS]** If random reward mainly acts through clipped self-distillation,
I's effect and any expansion of high-prior formatting/code modes should shrink
substantially without clipping. A B-S gap that survives no-clipping would
instead identify recipient-correlated gradient information. If both vanish,
the frozen-SFT effect was likely selection/curriculum rather than on-policy
gradient exploitation. If both persist, inspect KL, zero-advantage filtering,
and prompt allocation before attributing causality.

The analysis must report:

- every attempted group, valid \(V\), eligible \(K\), realized \(H\), and
  whether the group was mixed;
- raw attempts per optimizer step and empty-attempt frequency;
- strict/proxy gradient-carrying row composition;
- clipping fraction and update norm by assignment;
- common-attempt and common-step strict curves.

### 6.2 Iterative-SFT hysteresis test

The stronger nonlinear test is a bidirectional curriculum rather than a
one-way dose sweep.

1. Create two initial teachers: the clean base and a deliberately B-enriched
   teacher produced under a high, but nondegenerate, behavior-conditioned dose.
2. Sweep \(p_A\) upward from the clean teacher and downward from the enriched
   teacher over the same grid. Warm-start each round from the preceding teacher.
3. At every round, collect both a fixed raw bank and a fixed accepted count,
   preserving the B/S/G controls and clean anchors.
4. Train the same number of exact-cardinality updates, then evaluate clean
   strict OP11–45 and measure \(x=P(A)\), \(h\), prompt allocation, and the next
   round's effective trigger rate.
5. In parallel, train reset-from-base arms at every dose. These distinguish
   path dependence from ordinary differences in cumulative training time.
6. Reverse the sweep again or hold the dose constant long enough to determine
   whether an apparent loop is a transient lag.

**[HYPOTHESIS]** Endogenous hackability predicts different stable \(x\) and
strict performance at the same dose depending on approach direction, within
the interval \(\mu_B-\alpha<p_0<\mu_B\). Preregister loop area and same-dose
up/down endpoint differences as statistics.

The hysteresis hypothesis is falsified if up/down differences vanish after
matching cumulative accepted examples and allowing convergence, or if the
measured trigger susceptibility does not increase with \(x\). A persistent
loop in only proxy reward, without a corresponding behavior or clean-target
loop, is not evidence of the proposed mechanism.

### 6.3 Other high-value boundary tests

- **False positives versus false negatives:** match the absolute number of
  flips. The support theory predicts false positives can open a strict-dead
  region, while false negatives can only remove existing clean support.
- **Persistent versus resampled defects:** reuse prompt-slot draws versus add a
  visit index. Persistence should increase memorization/exploitation if prompts
  recur.
- **Difficulty-targeted versus behavior-targeted defects:** match marginal
  counts to separate curriculum rotation from trajectory-content alignment.
- **Group-size scaling:** vary \(K\in\{16,32,64,128\}\). The activation model
  predicts approximate collapse against \(Khp\), while clipping or optimizer
  effects need not.
- **Heavy-tail construction:** a separate graded-payoff environment could test
  the Kwa et al. asymptotic mechanism. It must not be presented as an
  explanation of the current bounded binary reward.

## 7. Candid novelty matrix

“Yes” means the feature is an explicit controlled object, not merely present
incidentally.

| Study | Behavior-specific recipient | Strict process target | Near-zero strict-dead test | Raw/update dual clocks | Iterative SFT | Clipping isolated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Rad et al. 2026 | No; class-conditional | No | Support barrier noted, no dose experiment | No | No | No |
| Cai et al. 2025/26 | No; treated as assumption violation | No | No | No | No | No |
| Shao et al. 2025/26 | Random/format rewards | No | Random \(p=0\) versus positive | No | No | Yes |
| Plesner et al. 2026 | Uncontrolled weak-verifier correlation | No | No | No | No | No |
| Li et al. 2026 | Feature-dependent preference noise | No | No | No | No | No |
| Helff et al. 2026 | Yes, deterministic shortcut | Analogous intensional target | No probability sweep | No | No | No |
| Pan et al. 2022 | Proxy-specific behavior | Environment true return | Capability threshold, not \(p\to0\) | No | No | No |
| Gao et al. 2022/23 | Reward-model proxy | Gold reward model | No; smooth scaling fits | Optimization strength | No | No |
| Uesato / Lightman / Wang | No injected defect | Yes | No | No | No | No |
| Current GSM-Infinite design | Yes: B/S/G/I decomposition | Yes | Yes, finite-bank OP21–40 gate | Yes | Fixed-count screen and planned iteration | Planned RL factorial |

The current design's strongest new contribution would be a causal decomposition
of four effects that prior curves mix together:

1. iid channel noise and clipping bias;
2. sparse hard-group activation;
3. prompt/task allocation;
4. trajectory-recipient alignment.

Its limitations are equally important:

- a finite frozen bank cannot prove population \(q=0\);
- three selection seeds are a screen, not a definitive scaling study;
- fixed-M SFT removes on-policy feedback by construction;
- B/S/G recipient distributions can still differ on unmeasured features;
- the current dose floor is not an empirical \(p\to0\) limit;
- a stable neural-network ceiling requires much longer training than a 64-step
  mechanistic screen;
- RL clipping and asynchronous attempt throughput require their own factorial.

## 8. Decision rules and present conclusion

Use the following language for eventual claims.

- **“Clock effect”** if a difference under raw exposure disappears or reverses
  at matched optimizer steps.
- **“Support discontinuity”** if C0 has no hard accepted data while every
  positive fixed-M arm has the same limiting hard-data distribution. This is
  already an algebraic property of the strict-dead rejection model, subject to
  the empirical gate.
- **“Behavior-recipient effect”** only if B differs reproducibly from S.
- **“Prompt-allocation effect”** only if S differs reproducibly from G and the
  measured allocation moves accordingly.
- **“Practical iid optimizer effect”** if I differs from C0 despite \(J>0\),
  especially if clipping controls it.
- **“Finite-time crossover”** if the apparent critical dose moves with time,
  group size, or raw exposure as predicted by \(pht\) or \(Khp\).
- **“Phase transition”** only with a stable nonanalytic/bistable signature:
  dose-to-zero separation that survives clock matching and longer horizons, or
  reproducible hysteresis at the same dose. A steep curve alone is not enough.

The evidence currently supports a narrower conclusion. Behavior-conditioned
false positives are theoretically capable of changing the selected behavior
distribution, and strict-dead fixed-count selection has an exact
zero-versus-positive support singularity. The legacy RL data demonstrate a
large update-throughput confound and a common-step penalty at 5%, but they do
not establish a phase transition or an altered asymptotic ceiling. The
preregistered B/S/G/I frozen-bank experiment is designed to determine which
part of any observed effect comes from recipient identity, prompt allocation,
global hard-sample support, or an iid noisy channel. The clipping factorial and
bidirectional iterative-SFT test are required before making the stronger
claims about practical GRPO or hysteresis.
