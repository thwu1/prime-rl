# Verifier defects, selection clocks, and strict-reasoning generalization

Status: research synthesis, live RL analysis, and preregistration, 2026-08-09.
This document is standalone. It distinguishes prior results, derivations made
for this study, observations from existing artifacts, and hypotheses that have
not yet been tested. The target throughout is clean strict dependency-graph
correctness, not the proxy reward optimized during training.

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

The literature and theory support eight conclusions.

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
   a discontinuity at zero. Yang et al. independently provide a more general
   active-wrong-label phase-boundary theorem under explicit coupling and drift
   assumptions.

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

5. **The constant-fitness replicator and first-order fixed-kernel terms do not
   generate hysteresis by themselves.** They can yield finite-time ratios
   proportional to \(\exp(cpt)\), finite-group discovery curves of the form
   \(1-\exp(-NCp^h)\), or a positive linear-stability crossing. Genuine
   bistability additionally requires state-dependent gain, such as behavior
   prevalence increasing future hackability or changing the learned transfer
   kernel. This separates a sharp dose curve from the bidirectional
   initialization test needed for a hysteresis claim.

6. **A separate perfect-versus-imperfect singularity is possible when a defect
   only seeds a lineage that can reproduce without another verifier error.**
   Let \(p\) control the immigration rate of accepted wrong-CoT lineages and
   let \(R_0=b/\mu\) be their post-seed reproduction-to-cure ratio. If
   \(R_0>1\), the perfect \(p=0\) process remains in its absorbing clean state,
   while any positive immigration field reaches an endemic bad-behavior state
   in the infinite-population, long-time limit. At finite size and time the
   response is smooth:

   \[
   P(\text{outbreak by }T)\simeq
   1-\exp[-L\nu p(1-R_0^{-1})(T-t_g)_+].
   \]

   This gives an exact route to an exponential-looking low-dose effect, but
   only if replay, optimizer memory, a quenched blind spot, or parameter
   transfer makes post-seed growth independent of \(p\). If every descendant
   must win a fresh \(p\)-coin, then \(b\) itself scales with \(p\) and the
   perfection singularity disappears.

7. **Verifier-filtered iterative SFT has an exact finite critical point.**
   If a round samples \(n\) candidates, uses an \(A\) target whenever one
   \(A\) candidate passes with probability \(p\), and the next model reproduces
   that target mixture, then

   \[
   x_{t+1}=1-(1-px_t)^n,\qquad p_c=\frac1n.
   \]

   With \(n=16\), 1% and 5% are subcritical while 10% is supercritical. Requiring
   two accepted \(A\) candidates instead creates a saddle-node: at \(n=128\),
   clean and high-\(A\) states coexist above \(p=2.6097\%\). These predictions
   require iterative fixed-raw selection and do not apply to the current RL
   runs or one-pass SFT.

8. **Persistent semantic blind spots can change asymptotic relaxation even
   before they change the stationary ceiling.** Quenched vulnerable
   neighborhoods can form exponentially rare, exponentially long-lived active
   regions, producing a Griffiths interval with non-universal power-law decay.
   Fresh coins cannot create the same rare-region memory. The mechanism
   requires a localized operation--template transfer kernel; dense rank-one
   sharing falsifies it. GSM-Infinite permits an exact 1/93 semantic-blind-spot
   versus random-prompt versus iid correlation-length screen without dynamic
   verifier state.

**[OBSERVATION—CURRENT; PRELIMINARY]** The live OP10–40 RL runs support a
finite-time group-activation/curriculum mechanism, not an exponential change
in final ceiling. Through optimizer step 4,000, normalized OP15–17 AUC was
14.588%, 13.337%, and 10.397% for \(p=0,1\%,5\%\). Under the post-hoc common
raw-exposure proxy \(E^*=3{,}175{,}552\), the same values were 13.053%,
12.964%, and 12.325%. The earlier apparent 1% raw-budget advantage has washed
out and changed sign, while its per-update deficit persists; the 5% arm is
worse on both AUC clocks. A frozen
audit through step 899 observed 0, 393, and 756 defect-only activated OP21–40
groups. All three arms remained at 0/1,000 on unseen OP41–45 at both selected
clocks. These are one-run-per-arm descriptive results, and the live evaluations
mix adjacent policy versions; they do not estimate a treatment-effect variance,
an asymptotic ceiling, or a phase transition.

**[OBSERVATION—FROZEN PREFLIGHT]** The proposed low-dose masked pairs match
expected aggregate activation within 0.31% in the exact scheduled-prefix
projection, while `L=32` removes all candidate eligibility from 14.26%–14.81%
of candidate-bearing frozen prompts. Exact analysis shows that this `K=0`
statistic is latent: the fourfold coin restores the candidate marginal and the
reward-vector laws differ only at `O(p^2)`, with worst-case total variation
below 0.0015 at the tested doses. The shuffled control is partial:
62.6%–64.9% of its frozen reward recipients still exhibit the target behavior.
The new minimum-behavior control reduces that fraction to 10.1%–11.3% while
reusing zero original triggers. These are now explicit manipulation checks
rather than post-hoc caveats.

The defensible novelty target is therefore not “noise can cause reward
hacking” or “misspecification can have phase transitions”; Yang et al. and
Egashira et al. now make both especially direct priors. It is to isolate how
*persistent, behavior-conditioned false positives* affect a clean process
target at an empirically strict-dead frontier after separately matching raw
exposure, accepted-example count, group activation, prompt allocation, and
optimizer steps.

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
| Pan, Bhatia, and Steinhardt, [*The Effects of Reward Misspecification: Mapping and Mitigating Misaligned Models*](https://arxiv.org/abs/2201.03544) (2022) | **[EMPIRICAL—PRIOR]** Five of nine proxy/environment pairs produced misalignment; four showed sharp qualitative transitions as model size, training time, action resolution, or observation quality increased. | Varies capability under a fixed proxy rather than defect probability, recipient identity, or selection clock; newer direct phase-boundary priors appear below. |
| Gao, Schulman, and Hilton, [*Scaling Laws for Reward Model Overoptimization*](https://arxiv.org/abs/2210.10760) (2022/2023) | **[EMPIRICAL—PRIOR]** Gold reward first rises and then falls with proxy optimization; reported fits are \(R_{\rm BoN}(d)=d(\alpha-\beta d)\) and \(R_{\rm RL}(d)=d(\alpha-\beta\log d)\). | The gold target is another reward model, and the fitted behavior is smooth rather than a perfection discontinuity. |
| Coste et al., [*Reward Model Ensembles Help Mitigate Overoptimization*](https://arxiv.org/abs/2310.02743) (2023/2024) | **[EMPIRICAL—PRIOR]** Conservative ensembles strongly reduce best-of-\(N\) and PPO overoptimization under injected label noise. | Preference reward models, not binary process verifiers or behavior-matched false positives. |
| Denison et al., [*Sycophancy to Subterfuge: Investigating Reward-Tampering in Large Language Models*](https://arxiv.org/abs/2406.10162) (2024) | **[EMPIRICAL—PRIOR]** Training on gameable environments increases later specification gaming and leaves a small nonzero rate of direct reward tampering. | A curriculum of qualitatively different environments, not a controlled \(p_A\) sweep. |
| Che and Wu, [*Greed Is Learned: Visible Incentives as Reward-Hacking Triggers*](https://arxiv.org/abs/2606.16914) (2026) | **[EMPIRICAL/THEORY—PRIOR]** Holds reward and optimizer fixed while comparing visible, hidden, and randomized reward channels. A three-seed decision-relevance sweep changes visible-channel OOD proxy seeking from 0 at reliability 1/3 to 0.035 at 0.45 and 0.480 at 0.55, while hidden/random controls remain zero; its formal criterion predicts a continuous response as channel information grows. | The closest visibility prior and an important novelty correction: hidden-versus-visible known-cost reward channels are not new. Its reliability is channel informativeness rather than verifier FPR, the main objective scores all action letters, and it has no strict-CoT oracle, dual clocks, gradient-transfer calibration, or hysteresis test. |
| Kwa, Thomas, and Garriga-Alonso, [*Catastrophic Goodhart: Regularizing RLHF with KL Divergence Does Not Mitigate Heavy-Tailed Reward Misspecification*](https://arxiv.org/abs/2407.14503) (2024) | **[THEOREM—PRIOR]** Sufficiently heavy-tailed proxy error can cause asymptotic catastrophic Goodhart despite KL regularization. | Bounded binary verifier rewards cannot realize the heavy-tail mechanism. “Any positive mixture weight inherits the bad tail” is a possible corollary for another environment, not a claim about GSM-Infinite. |
| Rakhsha et al., [*Policy Teaching via Environment Poisoning: Training-time Adversarial Attacks against Reinforcement Learning*](https://arxiv.org/abs/2003.12909) (2020) | **[THEOREM—PRIOR]** Gives conditions and cost bounds for reward/transition poisoning that induces a target policy. | Optimized adversarial perturbations, not stochastic, behavior-conditioned verifier errors. |
| Zhang et al., [*Adaptive Reward-Poisoning Attacks against Reinforcement Learning*](https://arxiv.org/abs/2003.12613) (2020) | **[THEOREM—PRIOR]** Establishes feasible/infeasible perturbation regimes and advantages for adaptive poisoning. | Its threshold concerns adversarial perturbation magnitude, not false-positive probability. |

### 2.3 Noisy RLVR and behavior-dependent verifier errors

| Work | Relevant result | Caveat for this study |
| --- | --- | --- |
| Rad et al., [*Rate or Fate? RLV\(^{\varepsilon}\)R: Reinforcement Learning with Verifiable Noisy Rewards*](https://arxiv.org/abs/2601.04411) (2026) | **[THEOREM—PRIOR]** In a mean-field, block-symmetric, small-step GRPO/replicator model, \(J>0\) makes correct modes attracting, \(J=0\) is neutral, and \(J<0\) makes incorrect modes attracting; zero initial correct support is separately absorbing. | January 2026 v1. The result assumes behavior-independent class-conditional noise and does not prove finite neural GRPO behavior with clipping and sparse groups. |
| Shang et al., [*When Errors Can Be Beneficial: A Categorization of Imperfect Rewards for Policy Gradient*](https://arxiv.org/abs/2604.25872) (2026) | **[THEOREM/EMPIRICAL—PRIOR]** Shows that initial policy mass and the gradient geometry of output features determine whether erroneous rewards attract or repel probability; marginal error rate alone is insufficient. | Its local policy-gradient categories do not by themselves establish a finite-time neural phase transition, but they directly motivate measuring cross-template gradient transfer rather than assuming independent modes. |
| Mroueh, [*GRPO's Effective Loss, Dynamics, and Success Amplification*](https://arxiv.org/abs/2503.06639) (2025) | **[THEOREM—PRIOR]** Derives distinct recurrences and smooth regularized fixed points for mean-only, variance-normalized, mirror, and fixed-reference-KL GRPO variants. | The configured DPPO masking, sampler-policy lag, token weighting, and optimizer are not identical to the analyzed idealizations; a fixed-reference KL term is not a constant behavior cost. |
| Cai et al., [*Reinforcement Learning with Verifiable yet Noisy Rewards under Imperfect Verifiers*](https://arxiv.org/abs/2510.00915) (2025/2026) | **[THEOREM—PRIOR]** Derives an unbiased correction \((\widetilde R-\rho_0)/(1-\rho_0-\rho_1)\) while the class-conditional channel is informative. The paper explicitly identifies a residual covariance term when errors depend on content. | Population REINFORCE-style analysis; content-dependent false positives violate its principal assumption. |
| Yang et al., [*Can LLMs Learn to Reason Robustly under Noisy Supervision?*](https://arxiv.org/abs/2604.03993) (2026) | **[THEOREM—PRIOR]** Separates inactive wrong labels from policy-realizable active wrong labels and derives an explicit critical active-noise ratio above which wrong solutions dominate, including a KL-shifted boundary. | The closest formal phase-boundary prior. Exact inactive support is unrealistic for softmax LMs; the result assumes constant positive cross-sample coupling, small steps, stable drift, and no clipping. Seed-level experiments are not reported. |
| El Mansouri et al., [*Noise-corrected GRPO*](https://arxiv.org/abs/2510.18924) (2025/2026) | **[THEOREM—PRIOR]** Derives group-specific corrections for unbiased clean-centered GRPO gradients and analyzes noisy fixed points. | Assumes class-conditional independent flips and known or estimated global rates; behavior-correlated defects fall outside the correction model. |
| Egashira et al., [*Delay, Plateau, or Collapse: Evaluating the Impact of Systematic Verification Error on RLVR*](https://arxiv.org/abs/2605.02909) (2026) | **[EMPIRICAL—PRIOR]** Controlled arithmetic RLVR shows systematic false negatives delay learning while deterministic behavior-conditioned false positives produce plateaus or collapse. Initial trigger frequency and oracle conditional advantage predict the regime better than marginal FPR. | The closest empirical mechanism prior. Triggers are deterministic rather than a `p_A` sweep; raw/update clocks, a strict-dead frontier, and seed replication are not supplied. |
| Tan et al., [*Breaking the Self-Confirming Loop: Diagnosing and Mitigating Systemic Reward Bias in Self-Rewarding RL*](https://arxiv.org/abs/2510.08977) (2025/2026) | **[EMPIRICAL—PRIOR]** Controlled arithmetic GRPO independently varies total reward-noise magnitude, false-positive/false-negative skew, and policy--reward coupling. It reports a sharp accuracy collapse between noise levels 0.4 and 0.5, greater damage from policy-dependent than policy-independent noise at matched magnitude, and greater damage from false positives than false negatives. | Intrinsic self-reward rather than a frozen binary verifier; the sharp curve is not a low-dose, bidirectional, replicated hysteresis demonstration. |
| Yu et al., [*Understanding and Mitigating Spurious Signal Amplification in Test-Time Reinforcement Learning for Math Reasoning*](https://arxiv.org/abs/2604.21327) (2026) | **[EMPIRICAL—PRIOR]** Identifies medium-consistency pseudo-labels as the main ambiguity region and shows that group-relative advantage estimation can amplify their spurious signal; fixed advantages and ambiguity filtering reduce the effect. | Test-time pseudo-label adaptation rather than long-horizon RLVR, but it makes group candidate count and consistency necessary manipulation checks. |
| Zhang, [*When the Reward Suite Is Leaky*](https://arxiv.org/abs/2607.11022) (2026) | **[EMPIRICAL—PRIOR]** In a preregistered leaky-versus-hardened code-verifier study, 47.6% of audited leaked reward paid wrong programs, yet the five-seed 400-step held-out gap was bounded and initial false-positive behaviors were selected rather than growing. | A useful counterexample: persistent correlated false positives need not measurably harm finite-horizon capability. Small models, short code tasks, nonnested verifier suites, and a sole-author preprint limit transfer. |
| Khalifa et al., [*Countdown-Code*](https://arxiv.org/abs/2603.07084) (2026) | **[EMPIRICAL—PRIOR]** A proxy-filtered SFT set with 1.2% hacking traces can seed later RL hacking and cross-benchmark transfer; some model families amplify hacking dramatically. | The 1.2% fraction is not a randomized threshold, models differ sharply, and contamination ablations also change clean-data count. Evidence for a small-contamination catalyst, not a zero-dose discontinuity. |
| Zhu and Kang, [*Noisy Data is Destructive to RLVR*](https://arxiv.org/abs/2603.16140) (2026) | **[EMPIRICAL—PRIOR]** Re-verification exposes mislabeled “wrong” targets; genuinely wrong policy-derived targets reduce performance and create a confirmation-bias loop. | Persistent annotation/target corruption rather than stochastic verifier false positives, with limited reported seed replication. |
| Rahman et al., [*When Can LLMs Learn to Reason with Weak Supervision?*](https://arxiv.org/abs/2604.18574) (2026) | **[EMPIRICAL—PRIOR]** Frequent model-specific wrong answers are used as persistent targets; robustness varies sharply by model and domain, with Qwen sometimes generalizing through high corruption. | Cross-model predictors are observational and some judgments are model-based; not a trajectory-level probabilistic verifier defect. |
| Huang et al., [*From Accuracy to Robustness*](https://arxiv.org/abs/2505.22203) (2025) | **[EMPIRICAL—PRIOR]** Static verifier accuracy can mispredict RL robustness: rule verifiers show policy-dependent false negatives, while some learned verifiers are exploited as proxy reward rises and oracle reward falls. | The oracle is imperfect, best checkpoints are emphasized, and there is no replicated defect-dose sweep. |
| Mitsuhashi et al., [*Quantifying Empirical Compute-Supervision Tradeoffs in RLVR*](https://arxiv.org/abs/2605.25252) (2026) | **[EMPIRICAL—PRIOR]** Independent FP/FN and 8/16/32-rollout sweeps find finite-compute gaps and, in their settings, false negatives can be more damaging. | One seed, small models, a narrow compute range, and smooth polynomial fits; no asymptotic-ceiling result. |
| Shao et al., [*Spurious Rewards: Rethinking Training Signals in RLVR*](https://arxiv.org/abs/2506.10947) (2025/2026) | **[EMPIRICAL—PRIOR]** Completely random rewards improved Qwen2.5-Math-7B substantially; removing clipping removed the consistent effect, and the result did not transfer uniformly across model families. The proposed clipping-bias mechanism uses a simplified objective and is explicitly a conjecture. | Directly refutes “iid rewards cannot matter in practical GRPO,” but it studies optimizer-induced self-distillation rather than a behavior-targeted verifier defect. |
| Plesner, Guzmán, and Athalye, [*An Imperfect Verifier is Good Enough: Learning with Noisy Rewards*](https://arxiv.org/abs/2604.07666) (2026) | **[EMPIRICAL—PRIOR]** Resampled symmetric noise up to 15% was often close to clean training; weak verifiers with low precision were exploited, suggesting false positives are particularly dangerous. | April 2026 v1. Persistent error and a controlled FP-versus-FN factorial are left open; some precision conclusions are observational. |
| Lv et al., [*The Climb Carves Wisdom Deeper Than the Summit: On the Noisy Rewards in Learning to Reason*](https://arxiv.org/abs/2505.22653) (2025) | **[EMPIRICAL—PRIOR]** Qwen retained much of its performance under substantial question-level reward inversion and collapsed around 50%; a phrase-based reward improved transiently and later overoptimized. | PPO with question/group-level noise, not recipient-matched trajectory false positives. |
| Li, Kethireddy, and Das, [*Evaluating Feature Dependent Noise in Preference-based Reinforcement Learning*](https://arxiv.org/abs/2601.01904) (2026) | **[EMPIRICAL—PRIOR]** Feature-, similarity-, and margin-dependent preference noise can damage methods that tolerate uniform noise. | Continuous-control preference RL, with no verifier-dose phase-transition result. |
| Helff et al., [*LLMs Gaming Verifiers: RLVR can Lead to Reward Hacking*](https://arxiv.org/abs/2604.15149) (2026) | **[EMPIRICAL—PRIOR]** A deterministic extensional-verifier loophole causes shortcut learning; an isomorphism-aware verifier removes it in one inductive-logic benchmark and controlled 7B setup. | A close behavioral analogue to `p_A`, but it compares deterministic verifiers rather than sweeping defect probability or matching raw/update clocks; cross-model comparisons are observational. |

### 2.4 Process supervision, inference verification, and iterative feedback

| Work | Relevant result | Caveat for this study |
| --- | --- | --- |
| Cobbe et al., [*Training Verifiers to Solve Math Word Problems*](https://arxiv.org/abs/2110.14168) (2021) | **[EMPIRICAL—PRIOR]** Sampling and verifier reranking improve GSM8K and scale effectively with data. | Outcome verification at inference, not corrupted-verifier training. |
| Uesato et al., [*Solving Math Word Problems with Process- and Outcome-Based Feedback*](https://arxiv.org/abs/2211.14275) (2022) | **[EMPIRICAL—PRIOR]** Process feedback can substantially reduce incorrect reasoning among final-answer-correct solutions, while outcome-trained reward models can emulate some process feedback and reach similar final-answer error. | The often-quoted 14.0% versus 3.4% comparison is a best-system/prior-work comparison, not a clean causal process-versus-outcome ablation. It still motivates strict CoT as the target. |
| Lightman et al., [*Let's Verify Step by Step*](https://arxiv.org/abs/2305.20050) (2023) | **[EMPIRICAL—PRIOR]** Process reward models outperform outcome reward models on MATH and support active-learning gains. | Learned verifier quality, not controlled error-recipient interventions. |
| Wang et al., [*Examining False Positives under Inference Scaling for Mathematical Reasoning*](https://arxiv.org/abs/2502.06217) (2025) | **[EMPIRICAL—PRIOR]** Correct-answer/incorrect-reasoning false positives contaminate pass@\(N\) increasingly as inference scales. | Inference evaluation rather than training dynamics. |
| Stroebl et al., [*The Limits of Inference Scaling Through Resampling*](https://arxiv.org/abs/2411.17501) (2024) and Dorner et al., [*ROC-n-reroll*](https://arxiv.org/abs/2507.12399) (2025) | **[THEOREM—PRIOR]** Formalize false-positive ceilings and verifier-ROC dependence under repeated sampling and discuss consequences for rejection-selected data. | Inference/resampling theory rather than on-policy training dynamics. |
| Xu et al., [*TinyV*](https://arxiv.org/abs/2505.14625) (2025) | **[EMPIRICAL—PRIOR]** Finds substantial rule-verifier false negatives and reports stronger RL after recovering rejected correct solutions. | Intervention false-positive rates are insufficiently characterized, so FN causality is not isolated cleanly. |
| Pan et al., [*Spontaneous Reward Hacking in Iterative Self-Refinement*](https://arxiv.org/abs/2407.04549) (2024) | **[EMPIRICAL—PRIOR]** Evaluator scores can improve while human quality stagnates or declines. Generator and evaluator use the same underlying model throughout; the controlled ablation changes whether their dialogue histories are shared. | Establishes iterative amplification, not a controlled `p_A -> 0` boundary; shortcut alignment from model identity is a hypothesis rather than the ablated variable. |
| Zhou, [*More Convincing, Not More Correct: Self-Play Reward Hacking of Reference-Free LLM Judges*](https://arxiv.org/abs/2607.05904) (2026) | **[EMPIRICAL—PRIOR]** GSM8K self-play raises judge pass from about 0.72 to 0.94 while exact match stays about 0.20 across three seeds. Candidate-conditioned FPR is 0.719 but falls to 0.012 when the same judge must commit independently first. A Gemma replication enters the hacking basin in three of five seeds, while two remain clean. | Strong evidence for verifier-coupled amplification and stochastic basin entry, but not a defect-dose phase transition: there is no randomized FPR dose, bidirectional initialization, long-horizon convergence, or hysteresis. |
| Perdomo et al., [*Performative Prediction*](https://arxiv.org/abs/2002.06673) (2020) | **[THEOREM—PRIOR]** Formalizes learning when deployed models change their own data distribution and distinguishes performatively stable from optimal points. Under its smoothness and strong-convexity conditions, repeated risk minimization is contractive when distribution sensitivity is below the curvature-to-smoothness boundary; counterexamples appear when the assumptions or boundary fail. | A general feedback framework, not verifier-specific GRPO; it supplies a unique-stable-state null, not evidence that policy dependence generically creates hysteresis. |
| Brown, Hod, and Kalemaj, [*Performative Prediction in a Stateful World*](https://arxiv.org/abs/2011.03885) (2022) | **[THEOREM—PRIOR]** Extends performative prediction so population response depends on both the deployed model and current population state, and gives convergence conditions for repeated retraining and a lazy variant. | Statefulness alone does not imply multiple basins or hysteresis; its response-map assumptions must be connected to measurable verifier-recipient dynamics. |
| Mandal, Triantafyllou, and Radanovic, [*Performative Reinforcement Learning*](https://arxiv.org/abs/2207.00046) (2023) | **[THEOREM—PRIOR]** Formalizes policy-dependent rewards and transitions and proves that repeated regularized optimization converges to a performatively stable policy when regularization dominates environment sensitivity; a projected-gradient variant is likewise contractive under explicit conditions. | Tabular occupancy-measure theory, not neural GRPO. It supplies a rigorous unique-stable-policy null rather than evidence that feedback generically creates hysteresis. |
| Pollatos, Mandal, and Radanovic, [*On Corruption-Robustness in Performative Reinforcement Learning*](https://arxiv.org/abs/2505.05609) (2025) | **[THEOREM/EMPIRICAL—PRIOR]** Under Huber \(\epsilon\)-contamination, a robust-gradient repeated-retraining method converges in the last iterate to an approximately stable policy with error proportional to \(\sqrt{\epsilon}\). | Studies a corruption-aware algorithm and adversarial sample contamination, not ordinary training with behavior-conditioned verifier recipients; it provides a smooth small-corruption baseline. |
| Dong, Zhang, and Ratliff, [*Approximate Regions of Attraction in Learning with Decision-Dependent Distributions*](https://arxiv.org/abs/2107.00055) (2023) | **[THEOREM—PRIOR]** Gives sufficient conditions under which inexact repeated risk minimization converges to neighborhoods of distinct local performative-risk minima and characterizes subsets of their initialization-dependent attraction regions. | Establishes basin and warm-start methodology under curvature and perturbation assumptions, but neither verifier defects nor a dose-sweep hysteresis loop. |
| Piliouras and Yu, [*Multi-agent Performative Prediction: From Global Stability and Optimality to Chaos*](https://arxiv.org/abs/2201.10483) (2023) | **[THEOREM—PRIOR]** Constructs multi-agent performative-prediction systems with transitions from global stability to instability and formal chaos as update rates become less cautious. | The control parameter is multi-agent learning dynamics, not verifier false-positive probability; feedback phase transitions themselves are not new. |
| Gauthier, Bach, and Jordan, [*Explaining and Preventing Alignment Collapse in Iterative RLHF*](https://arxiv.org/abs/2605.04266) (2026) | **[THEOREM/EMPIRICAL—PRIOR]** Under a differentiable unique reward-model best response, decomposes the policy gradient into the usual proxy term and a parameter-steering term induced by future reward-model updates; a special linear model has a provably suboptimal myopic equilibrium, with controlled and Llama-3.2-1B demonstrations. | Does not prove universal iterative-RLHF collapse, sweep verifier-defect probability, or test hysteresis. Its mechanism requires a retrained reward model and is absent from a frozen exogenous verifier coin. |
| Ferbach et al., [*Self-Consuming Generative Models with Curated Data Provably Optimize Human Preferences*](https://arxiv.org/abs/2407.09499) (2024) | **[THEOREM—PRIOR]** Reward-based curation in iterative retraining acts as implicit preference optimization, amplifies reward-model bias, and can be stabilized by retaining positive real-data mass. | Generic generative-model recursion, not reasoning trajectories or a verifier-dose experiment. |
| Qiao et al., [*When Sample Selection Bias Precipitates Model Collapse*](https://arxiv.org/abs/2606.13732) (ICML 2026) | **[THEOREM/EMPIRICAL—PRIOR]** An imperfect local-reference selector can accelerate recursive collapse and power-law diversity decay. | Gaussian theory plus image/text generation, not strict reasoning SFT. |
| Song et al., [*When AI Reviews Its Own Code*](https://arxiv.org/abs/2606.28438) (2026) | **[EMPIRICAL—PRIOR]** Recursive SFT with a model-coupled gate can enter a rubber-stamp regime where acceptance rises while correctness falls. | Limited seed-level uncertainty; the theoretical gate-collapse statement is conditional and the “human” filters are compile/static checks. |
| Wu et al., [*Why Self-Training Helps and Hurts*](https://arxiv.org/abs/2602.14029) (2026) | **[THEOREM—PRIOR]** Overparameterized linear self-training has a U-shaped denoising-versus-signal-forgetting trajectory. | Useful basin and early-stopping theory, not verifier-defect evidence. |
| Shumailov et al., [*The Curse of Recursion*](https://arxiv.org/abs/2305.17493) (Nature 2024); Alemohammad et al., [*Self-Consuming Generative Models Go MAD*](https://arxiv.org/abs/2307.01850) (2023); Gerstgrasser et al., [*Is Model Collapse Inevitable?*](https://arxiv.org/abs/2404.01413) (2024) | **[THEOREM/EMPIRICAL—PRIOR]** Replacement versus accumulation of clean data qualitatively changes recursive-training stability. | Canonical controls for iterative SFT, but none studies behavior-conditioned verifier errors. |
| Burns et al., [*Weak-to-Strong Generalization: Eliciting Strong Capabilities with Weak Supervision*](https://arxiv.org/abs/2312.09390) (2023) | **[EMPIRICAL—PRIOR]** Strong models can exceed weak supervisors but generally do not recover the full strong ceiling; confidence-based methods help. | Weak labels are not the same as a sparse, behavior-correlated binary defect. |
| Kirchner et al., [*Prover-Verifier Games Improve Legibility of Language Model Outputs*](https://arxiv.org/abs/2407.13692) (2024) | **[EMPIRICAL—PRIOR]** Adversarial prover-verifier training can improve helpful accuracy and verifier robustness. | Changes the verifier through a game rather than holding a defect channel fixed. |
| Oymak and Gulcu, [*Statistical and Algorithmic Insights for Semi-supervised Learning with Self-training*](https://arxiv.org/abs/2006.11006) (2020) | **[THEOREM—PRIOR]** Finite-sample self-training recurrences can have suboptimal fixed points; confidence and margin matter. | Supports basin phenomena in iterative SFT but does not study verifier false-positive dose. |
| Frei et al., [*Self-training Converts Weak Learners to Strong Learners in Mixture Models*](https://arxiv.org/abs/2106.13805) (2022) | **[THEOREM—PRIOR]** Under explicit mixture-model separation and weak-initialization conditions, iterative pseudo-labeling can convert a weak classifier into a strong one. | The theorem supplies an initialization-threshold analogue, not verifier-correlated errors or an LLM iterative-SFT phase transition. |
| Arazo et al., [*Pseudo-Labeling and Confirmation Bias in Deep Semi-Supervised Learning*](https://arxiv.org/abs/1908.02983) (2020) | **[EMPIRICAL—PRIOR]** Demonstrates confirmation bias from erroneous pseudo-labels and mitigates it with mixup and a minimum share of labeled data in each minibatch. | Offline image classification, but it motivates retained-clean-data controls and direct tracking of error-class amplification in iterative SFT. |
| Hinrichsen, [*Non-equilibrium Critical Phenomena and Phase Transitions into Absorbing States*](https://arxiv.org/abs/cond-mat/0001070) (2000), reviewing the contact process originating with Harris (1974) | **[THEOREM/CONCEPT—PRIOR]** Contact processes have an absorbing inactive state, a reproduction-controlled active-state transition, finite-size metastability, and a conjugate immigration field that rounds the transition. A supercritical birth--death lineage survives with positive probability, while a finite system without immigration eventually becomes extinct. | The mathematics and critical exponents are standard, not a novelty claim. The verifier-specific question is whether an accepted wrong-CoT lineage has a measurable post-seed offspring number independent of further verifier errors; ordinary resampled reward coins need not have that property. |
| Vojta and Dickison, [*Critical Behavior and Griffiths Effects in the Disordered Contact Process*](https://arxiv.org/abs/cond-mat/0505354) (2005) | **[EMPIRICAL/THEORY—PRIOR]** Large one-dimensional simulations with quenched spatial disorder find an infinite-randomness critical point and a Griffiths region with power-law relaxation and continuously varying exponents. | Requires persistent spatially localized disorder and enormous time/system scales. A globally shared neural feature or freshly redrawn verifier coin does not satisfy the mechanism. |
| Vojta, [*Rare Region Effects at Classical, Quantum, and Non-equilibrium Phase Transitions*](https://arxiv.org/abs/cond-mat/0602312) (2006) | **[THEORY REVIEW—PRIOR]** Rare quenched regions can create essential singularities, anomalously slow dynamics, or smear a sharp transition when their lifetime grows faster than their occurrence probability shrinks. | Standard rare-region theory, not an LLM result. The new empirical question is whether semantic task neighborhoods act as localized, repeatedly vulnerable regions under shared model parameters. |

### 2.5 Label-noise results that delimit the analogy

| Work | Relevant result | Caveat for this study |
| --- | --- | --- |
| Patrini et al., [*Making Deep Neural Networks Robust to Label Noise: A Loss Correction Approach*](https://arxiv.org/abs/1609.03683) (2016/2017) | **[THEOREM—PRIOR]** Known class-dependent transition matrices permit forward/backward loss correction; **[EMPIRICAL—PRIOR]** experiments validate the method. | Requires a stable, identifiable class-level channel; behavior-conditioned policy data are endogenous. |
| Liu and Tao, [*Classification with Noisy Labels by Importance Reweighting*](https://arxiv.org/abs/1411.7718) (2014/2016) | **[THEOREM—PRIOR]** Importance weighting can recover consistency under independent binary label flips below the uninformative boundary. | Supervised iid inputs do not include policy-induced covariate shift or group advantages. |
| Menon et al., [*Learning from Binary Labels with Instance-Dependent Corruption*](https://arxiv.org/abs/1605.00751) (2016) | **[THEOREM—PRIOR]** Gives consistency results for particular instance-dependent corruption models and ranking conditions. | The assumptions are restrictive and do not cover arbitrary exploitable verifier behavior. |
| Cheng et al., [*Learning with Instance-Dependent Label Noise: A Sample Sieve Approach*](https://arxiv.org/abs/2010.02347) (2020) | **[THEOREM—PRIOR]** Filtering can be robust under stated separation assumptions; **[EMPIRICAL—PRIOR]** experiments study a sample-sieve implementation. | Offline classification; the filter does not alter a data-generating policy. |
| Liu et al., [*Identifiability of Label Noise Transition Matrix*](https://arxiv.org/abs/2202.02016) (2022) | **[THEOREM—PRIOR]** Generic instance-level transition matrices are not identifiable from one noisy label without additional assumptions or repeated labels. | Explains why aggregate FPR alone cannot recover our behavior-conditioned channel. |
| Chowdhury et al., [*Provably Robust DPO: Aligning Language Models with Noisy Feedback*](https://arxiv.org/abs/2403.00409) (2024) | **[THEOREM—PRIOR]** Under random flips \(\epsilon<1/2\), robust DPO bounds degrade with the familiar \(1/(1-2\epsilon)\) factor. | Pairwise offline preferences, not GRPO or strict-dead rejection sampling. |

### 2.6 Literature synthesis

Prior work already establishes all of the following: reward corruption can
break RL; proxy optimization can cause smooth overoptimization or sharp
capability thresholds; iid random rewards can matter under clipped GRPO; and
feature-dependent errors can be worse than uniform errors. Che and Wu already
show that a visible decision-relevant reward channel can separate sharply from
hidden/random controls under a reliability sweep, and Zhou already shows
seed-dependent entry into a verifier-hacking basin. Yang et al. already
derive an active-noise phase boundary, and Egashira et al. already demonstrate
systematic false-positive plateau/collapse regimes. Conversely, Zhang's
five-seed code study shows that abundant persistent false-positive reward can
select pre-existing errors without measurably degrading short-horizon held-out
capability. Performative prediction and performative RL additionally provide a
rigorous null: sufficiently weak policy--environment feedback relative to
curvature or regularization is contractive and has one stable solution, while
decision-dependent systems outside that regime can have multiple attraction
regions or even unstable dynamics. No novelty claim should be based on any one
of those statements.

The implemented persistent coin is a fixed misspecified reward, not a
co-adaptive verifier. It changes which trajectories receive reward as the
policy distribution changes, but it has no reward-model best response and no
parameter-steering gradient through future verifier updates. Results from
self-rewarding or iterative-RLHF feedback therefore motivate a separate
co-adaptive arm; they cannot be used to claim that the frozen coin itself
contains that mechanism.

The remaining gap is narrower and operational: no work in this map jointly
uses a semantically neutral susceptibility feature that must be learned from
sparse verifier errors, matches its marginal event law and explicit behavior
cost to a hidden gate, measures its cross-feature gradient-transfer kernel,
and evaluates strict process correctness at both raw-rollout and optimizer
clocks with a bidirectional hysteresis follow-up. The proposed contribution is
that joint causal decomposition and clock-controlled scaling test, not the
generic existence of correlated-noise or visible-incentive regimes.

A second, explicitly prospective gap is to distinguish *nucleation* from
*propagation*. Absorbing-state and branching-process theory already establish
the transition mathematics. What is not established for verifier-trained
reasoning models is whether one accepted wrong-CoT lineage can create more
than one inheritable descendant through replay or cross-task parameter
transfer after the defect is switched off. Measuring that longitudinal
offspring number and intervening on the propagation memory would be the
contribution; merely fitting a contact-process curve would not be.

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

**[THEOREM—PRIOR]** Yang et al. derive the closely related active-noise
boundary `rho_c = gamma G_c / (gamma G_c + G_n)`: above it, policy-realizable
wrong labels dominate under their coupling/drift assumptions, with a shifted
boundary under KL regularization. That result predates and subsumes the generic
claim that active wrong support can have a threshold. The derivation here is
useful only as the simpler behavior-mode mapping for this experiment. Yang et
al.'s exact inactive-support assumption is not literal for a softmax language
model, and their theorem does not include clipping, sparse 128-rollout group
activation, raw/update clock separation, or an evolving verifier-recipient
distribution.

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

### 3.5 Exact-size masking is a second-order dependence intervention

The masked Stage-1 pairs need a more precise interpretation. Fix a group with
\(C\) behavior candidates and let \(p\) denote each candidate's *marginal*
false-positive probability. The `L=128` arm has

\[
H_{128}\sim\operatorname{Binomial}(C,p).
\]

The matched `L=32` arm samples exactly 32 of 128 physical slots without
replacement and uses conditional coin probability \(4p\). Therefore

\[
K\sim\operatorname{Hypergeom}(128,C,32),\qquad
H_{32}\mid K\sim\operatorname{Binomial}(K,4p).
\]

Its probability-generating function is

\[
G_{32}(z)=\sum_k
\frac{\binom Ck\binom{128-C}{32-k}}{\binom{128}{32}}
(1-4p+4pz)^k.
\]

Both arms have exactly \(E[H\mid C]=Cp\). For two distinct candidate slots,
however,

\[
\operatorname{Cov}(Z_i,Z_j)=-\frac{3p^2}{127}
\]

under the size-32 mask, versus zero for independent size-128 coins. Hence

\[
P(H_{32}>0)-P(H_{128}>0)
=\binom C2\frac{3p^2}{127}+O(C^3p^3).
\]

**[DERIVATION—HERE]** The two reward-vector laws are exchangeable and,
conditional on \(H=h\), uniform over the same \(h\)-subsets. Their vector total
variation therefore equals the total variation between the two count laws.
Exact enumeration over \(C\le128\) gives worst-case distances of only
\(4.73\times10^{-4}\) at \(p=0.00125\) and \(1.48\times10^{-3}\) at
\(p=0.0025\). At \(C=7\), the corresponding values are
\(1.54\times10^{-6}\) and \(6.09\times10^{-6}\).

This resolves an initially misleading diagnostic. A size-32 mask can have
\(K=0\) on roughly 14.5% of candidate-bearing frozen prompts, yet the fourfold
conditional coin almost exactly restores the reward law. \(K=0\) is latent;
the policy observes only realized reward. Likewise, under the current shared
hash coupling, a candidate reward overlaps across arms with probability only
\(p/4\), so the rare-event Jaccard approaches \((1/4)/(2-1/4)=1/7\) even when
the marginal laws are nearly identical. Low activated-set overlap is a weak
common-random-number coupling, not evidence of large distributional distance.

The `L=128` versus `L=32` contrast is consequently a delicate test of whether
training adaptively amplifies a tiny \(O(p^2)\) change in within-group negative
dependence. Three seeds have little power because realized arm mismatches occur
at \(O(p)\) under the chosen coupling. A reproducible large effect would be
striking, but it would not establish a generic “support concentration” law.

### 3.6 Fixed-count rejection SFT: exact cancellation of defect magnitude

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

For disjoint incorrect behavior classes \(A_i\), let \(h_i^{(t)}\) be their
policy masses during collection round \(t\), and let \(p_i=\epsilon c_i\).
Then

\[
P(A_i\mid Z=1)
=\frac{c_i h_i^{(t)}}{\sum_j c_jh_j^{(t)}},\qquad \epsilon>0.
\]

The global error scale \(\epsilon\) cancels from the accepted-class
distribution, while the expected raw collection cost in round \(t\) is

\[
\frac{1}{\epsilon\sum_jc_jh_j^{(t)}}.
\]

To define an iterative select-and-imitate map without double-counting the
current class mass, write \(h_i^{(t)}=a_i x_i^{(t)}\), where \(x_i^{(t)}\) is
the policy mass of mode \(i\) and \(a_i\) is fixed within-mode candidate
accessibility. Exact imitation gives

\[
x_i^{(t+1)}
=\frac{c_i a_i x_i^{(t)}}{\sum_j c_j a_j x_j^{(t)}},
\qquad
x_i^{(t)}
=\frac{x_i^{(0)}(c_i a_i)^t}
       {\sum_jx_j^{(0)}(c_j a_j)^t}.
\]

If each behavior class is itself the candidate mode, set \(a_i=1\). Unequal
\(c_i a_i\) can then produce winner-take-all selection even as
\(\epsilon\to0^+\). This idealized recurrence assumes exact imitation and
fixed accessibility; it omits model generalization and policy-dependent
changes in \(a_i\).

The cancellation holds only under its conditioning. At fixed raw exposure,
the number accepted is random and vanishes with \(p_A\). If clean-positive
strata are mixed in, their accepted mass does not vanish, so the hard-stratum
share goes to zero with \(p_A\). Policy feedback can also change \(h\) between
rounds.

### 3.7 Base-rate frontier

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

### 3.8 Endogenous hackability and a genuine hysteresis construction

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

### 3.9 Persistent susceptibility can cross a threshold at fixed marginal FPR

The G--T experiment has a simple prediction that is stronger than “correlated
noise is worse.” Let \(x_j\) be the probability of behavior A on template
\(j\), let \(c>0\) be a constant exogenous clean-fitness disadvantage, and
write \(\ell_j=\operatorname{logit}(x_j)\). In a deliberately idealized
replicator approximation, a prompt-random, non-legible group gate G gives every
template the same mean verifier bonus \(p\):

\[
\ell_j^{G}(t)=\ell_0+\eta(p-c)t.
\]

For T, one of three visible templates is persistently vulnerable. Its
conditional bonus is \(3p\), while the other two receive none:

\[
\ell_{\rm selected}^{T}(t)=\ell_0+\eta(3p-c)t,
\qquad
\ell_{\rm other}^{T}(t)=\ell_0-\eta ct.
\]

This algebra assumes independent template logits, a constant exogenous
disadvantage \(c\) in the same units as expected verifier reward, exact
mean-gradient dynamics, and ex-ante randomization of the vulnerable template.
It is not a theorem about the configured GRPO optimizer. That optimizer has no
explicit KL penalty, shares parameters across templates, and includes
clipping, off-policy batches, and Adam; on a strict-dead group, a prompt-local
clean competitor may be absent, making the effective \(c\) close to zero until
strict competitors or cross-prompt parameter coupling appear. Consequently
\(c\) must be estimated from clean or near-clean log-odds drift. The boundary
below is a falsifiable organizing hypothesis, not a quantitative prediction
licensed by the configuration alone.

More generally, with gate probability \(\alpha\), T's selected-template bonus
is \(p/\alpha\), so the opposite-drift window is
\(\alpha c<p<c\). The factor three below is only the specialization
\(\alpha=1/3\). A fixed-reference KL penalty would instead contribute a
state-dependent term such as
\(-\beta(\ell-\ell_{\rm ref})\), producing a smooth regularized fixed point
rather than a constant subtractive \(c\).

Both mechanisms have the same per-candidate marginal FPR over the randomized
template assignment. Nevertheless, in the interval

\[
\boxed{c/3<p<c,}
\]

G suppresses A on every template while T amplifies it on the vulnerable
template. If A trades away strict process correctness, T can therefore cause a
template-specific strict collapse at a nominal FPR for which the equally
bursty G arm remains below threshold. This is a candidate phase-boundary
hypothesis conditional on \(c>0\) and sufficiently template-local parameter
transfer; it comes from persistent, observable susceptibility, not from the
marginal error rate or reward-count variance alone.

The shared neural parameterization is a major falsifier. In the local linear
model

\[
\dot{\boldsymbol\ell}=\eta K(\mathbf r-\mathbf c),
\]

the derivation above takes the cross-template gradient-transfer kernel
\(K\approx I\). If A is represented by one fully shared direction, T's average
bonus is \((3p+0+0)/3=p\), the same as G, and the threefold boundary can
disappear. Moreover, \(A=\) answer-correct/strict-wrong is an event over
heterogeneous trajectories rather than a stationary action: an update can
convert some A trajectories into strict solutions. Both \(K\) and conversion
must therefore be measured.

The finite-time weak-dose expansion is also informative. With
\(u=\eta pt\) and \(z=\ell_0-\eta ct\),

\[
x_G=\sigma(z+u),\qquad
\bar x_T=\frac{\sigma(z+3u)+2\sigma(z)}3,
\]

so

\[
\bar x_T-x_G=u^2\sigma''(z)+O(u^3).
\]

The first-order response matches; persistence appears at second order unless
the cost threshold is crossed. When A is initially rare,
\(\sigma''(z)>0\), concentration accelerates it; after A exceeds one half the
curvature reverses. Behavior odds themselves change as
\(\exp[\eta(3p-c)t]\), which explains an apparently exponential sensitivity to
small \(p\) over time. It does **not** imply a generic exponential dependence
of the final strict ceiling on \(p\). The empirical tests are therefore the
selected-versus-unselected template curves, movement of the apparent boundary
with \(t\), and G--T at matched raw and update clocks.

Even an exactly threefold apparent threshold ratio is not sufficient evidence
of a phase transition. For a finite-time target \(x_*\), define
\(D=\operatorname{logit}(x_*)-\ell_0\). The smooth logistic model itself gives

\[
p_{\rm app}^{G}(t)=c+\frac{D}{\eta t},\qquad
p_{\rm app}^{T}(t)=\frac{c+D/(\eta t)}{3}.
\]

Their ratio is three at every \(t\). The stronger prediction is convergence of
the two intercepts to a separately known \(c\) and \(c/3\); their finite-time
offsets decay as \(1/t\). If \(c=0\), both apparent boundaries drift to zero,
which is smooth amplification rather than a stable positive critical point.

### 3.10 A structural null for exponential-looking growth and hysteresis

The known-cost intervention permits a sharper null model. Let \(A\) denote an
answer-correct/strict-wrong trajectory, \(W\) an answer-wrong trajectory, and
\(S\) a strict trajectory. For group size \(n=128\), visible fraction
\(\alpha=1/3\), and tax \(c_0=0.03\), the isolated expected reward
differences are

\[
u_G(p)=r_A-r_W=p-c_0,
\qquad
u_{T,j}(p)=g_j\frac{p}{\alpha}-c_0,
\]

where \(g_j=1\) on a selected visible tag and zero otherwise. The frozen doses
therefore imply

| marginal \(p\) | hidden G | selected T | unselected T |
| ---: | ---: | ---: | ---: |
| 0.0075 | -0.0225 | -0.0075 | -0.0300 |
| 0.0125 | -0.0175 | +0.0075 | -0.0300 |
| 0.0225 | -0.0075 | +0.0375 | -0.0300 |
| 0.0375 | +0.0075 | +0.0825 | -0.0300 |

Thus the isolated injected channel crosses zero at \(p=0.03\) for G and at
\(p=\alpha c_0=0.01\) for selected T. These are reward-law calibration
points, not predictions for total strict performance: an accessible strict
trajectory has reward difference \(r_A-r_S=u-1<0\) at every frozen dose, and
shared gradients, candidate accessibility, clipping, and optimizer state add
unknown terms.

**[DERIVATION—HERE]** In an ideal iid group with score
\(s_i=\nabla\log\pi(\tau_i)\), mean-only GRPO centering obeys

\[
\mathbb E\left[\frac1n\sum_i(r_i-\bar r)s_i\right]
=\left(1-\frac1n\right)\mathbb E[r s].
\]

The factor is \(127/128\) here. Centering alone therefore neither creates a
new population threshold nor positive feedback. In the tabular two-mode
limit, the replicator approximation gives

\[
\frac{d}{dt}\log\frac{x_A}{x_W}
=\eta\frac{127}{128}u,
\]

Relative to dose zero, A/W odds therefore scale as \(\exp(cpt)\), with
\(c=\eta(127/128)\) for G and \(c=\eta(127/128)/\alpha\) for selected T in
this isolated model. The response remains analytic in \(p\) at every fixed
time. If the zero-dose direction is strictly stable, sufficiently small \(p\)
leaves the basin unchanged. If it is exactly neutral, the
\(p\to0\) and \(t\to\infty\) limits can fail to commute and the escape time is
\(O(1/p)\); that is a zero-threshold support or stability boundary, not a
generic perfection discontinuity.

The fixed-kernel extension makes the population test explicit. For a small
vector of per-tag A amplitudes \(\mathbf x\), write

\[
\dot{\mathbf x}=M_F(p)\mathbf x+O(\|\mathbf x\|^2),
\qquad
M_F(p)=B+\eta\frac{127}{128}K D_0\operatorname{diag}(\mathbf u_F(p)),
\]

where \(B\) is clean strict/optimizer drift, \(D_0\) contains initial
candidate-frequency and self-gradient scales, and \(K\) is the measured
cross-tag gradient-transfer kernel. A positive critical dose without
hysteresis can begin at a simple crossing of the spectral abscissa
\(\lambda_F(p)=\max\operatorname{Re}\operatorname{eig}M_F(p)\). The crossing
locates only a local stability boundary; the nonlinear terms determine whether
the branch is supercritical, subcritical, or globally bistable. One
non-hysteretic supercritical center-manifold normal form is

\[
\dot X=X\{a(p-p_c)-\gamma X\},\qquad a,\gamma>0.
\]

It has no bistable interval for positive-support initializations. The exact
\(X=0\) state remains invariant even when unstable, while exploration or
mutation adds positive support and rounds the crossing into a smooth
crossover.

The constant-fitness two-mode model and its first-order fixed-\(K\) extension
do **not** generate bistability by themselves. A minimal hysteretic normal
form needs an additional state-dependent gain,

\[
\dot X=X\{s(p)+\beta X-\gamma X^2\},
\qquad \beta,\gamma>0.
\]

For \(-\beta^2/(4\gamma)<s(p)<0\), low and high stable states coexist around
an unstable separator. If \(s(p)=a(p-p_{\rm up})\), the downward boundary is

\[
p_{\rm down}=p_{\rm up}-\frac{\beta^2}{4\gamma a}<p_{\rm up}.
\]

The required \(\beta\) could arise if A prevalence increases future candidate
accessibility, if specialization changes \(K\), or if clipping/filtering
creates a hard state-dependent switch. Alternatively, the parameterized
dynamics may already contain two representational basins and initialization
only selects between them. These mechanisms must be measured; they are absent
from the exogenous reward coin itself.

Finite groups supply a separate sharp-looking mechanism. Conditional on \(C\)
A candidates in a group,

\[
P_G(H>0\mid C)=\alpha\left[1-\left(1-\frac p\alpha\right)^C\right],
\]

with the bracketed term applying to a selected T tag and zero to an
unselected tag. Under an iid-slot approximation, across \(N\) groups with
candidate rate \(x\), the small-dose discovery probability is approximately

\[
P(\text{any trigger})\simeq1-\exp(-N\,128xp).
\]

If basin entry needs \(h\) coincident defect events, the leading rate becomes
\(p^h\). Such a knee must move with \(N\), group size, or cumulative realized
\(H\); it is not a fixed population critical dose.

These equations yield direct falsification tests. Early selected-minus-
unselected localization divided by \(p\) should follow the three
counterbalanced projections of the frozen \(K\). Under the fixed-K null,
curves should collapse after matching optimizer exposure and the per-tag
vectors of realized \(H\) and \(H-c_0C\) projected through \(K\); matching
only their scalar totals is insufficient. Systematic state-dependent growth
of the normalized response falsifies the fixed-K
first-order null but does not by itself establish bistability. Only distinct
long-dwell states at the same dose from clean and A-enriched initializations,
with reproducible \(p_{\rm down}<p_{\rm up}\), support hysteresis. The current
single-initialization pilot cannot make that claim.

### 3.11 Defect-seeded replay contagion: an absorbing-state transition

The preceding models make every unit of growth pay the verifier-defect
probability. There is a qualitatively different regime if a verifier error
only *nucleates* a persistent wrong-CoT lineage, after which replay, optimizer
memory, a quenched blind spot, or cross-task parameter transfer can reproduce
that lineage without another verifier error.

**[HYPOTHESIS; STANDARD CONTACT-PROCESS DYNAMICS, NEW VERIFIER MAPPING]** Divide
the training frontier into \(L\) operation--template neighborhoods. Let \(Z\)
be the number containing an inheritable lineage descended from a
verifier-accepted wrong-CoT sample. A raw answer-correct/strict-wrong sample is
not a lineage until the defect has selected it and its descendants are tracked
causally. Consider the finite continuous-time chain

\[
Z\to Z+1\quad\text{at rate}\quad
(L-Z)\left(\nu p+b\frac ZL\right),
\qquad
Z\to Z-1\quad\text{at rate}\quad \mu Z.
\]

Here \(\nu p\) is exogenous verifier-defect immigration, \(b\) is post-seed
transfer or replay, and \(\mu\) is clean correction or forgetting. The
coefficient \(\nu\) includes the policy's baseline rate of producing eligible
\(A\) candidates; if that support is exactly zero, defects cannot seed a
lineage at any \(p\). The crucial assumption is that \(b\) does not require a
fresh \(p\)-coin. It is a measured mechanism claim, not something obtained by
silently switching from raw time to an accepted-update clock.

For \(m=Z/L\), the mean-field flow is

\[
\dot m=(\nu p+bm)(1-m)-\mu m.
\]

Writing \(h=\nu p\), \(a=b-\mu-h\), and

\[
D=\sqrt{a^2+4bh},
\]

the unique physical fixed point for \(p>0\) is

\[
m_*(p)=\frac{b-\mu-\nu p+
\sqrt{(b-\mu-\nu p)^2+4b\nu p}}{2b},
\]

with local eigenvalue \(-D<0\). The post-seed reproduction number is

\[
R_0=\frac b\mu.
\]

The small-field laws are

\[
m_*(p)=
\begin{cases}
\dfrac{\nu p}{\mu-b}+O(p^2), & b<\mu,\\[6pt]
\sqrt{\dfrac{\nu p}{b}}+O(p), & b=\mu,\\[8pt]
1-\dfrac\mu b+
\dfrac{\mu\nu p}{b(b-\mu)}+O(p^2), & b>\mu.
\end{cases}
\]

At the threshold \(R_0=1\), the external-field exponent is \(1/2\) and the
relaxation time diverges as

\[
\tau_{\rm relax}\sim\frac{1}{2\sqrt{b\nu p}}.
\]

Above threshold, \(p=0,m(0)=0\) remains exactly absorbing, while the
positive-field stationary limit approaches the endemic density
\(m_0=1-\mu/b\):

\[
\boxed{
\lim_{p\downarrow0}\lim_{t\to\infty}m(t,p)=1-\frac\mu b
\ne
\lim_{t\to\infty}\lim_{p\downarrow0}m(t,p)=0.}
\]

This is a genuine absorbing-state perfection boundary conditional on
\(R_0>1\), rather than the constant-fitness \(pt\) amplification in Section
3.3. It is not hysteresis: for every \(p>0\) this scalar model has one stable
fixed point. Bistability would require another nonlinear feedback.

A triangular strict-performance readout makes the ceiling implication
explicit. If \(C\) is strict-CoT performance and

\[
\dot C=\gamma(\bar C-C)-d_m mC,
\]

then

\[
C_*(m)=\frac{\gamma\bar C}{\gamma+d_m m}.
\]

For \(R_0>1\), perfect verification tends to \(\bar C\), whereas the
\(p\downarrow0^+\) endemic ceiling tends to
\(\gamma\bar C/[\gamma+d_m(1-\mu/b)]\). This conclusion is conditional on the
lineage model and independently measured \(d_m>0\); the displayed readout
assumes degradation rather than deriving it from RL. It is not an observed
GSM-Infinite ceiling.

Finite size prevents an overclaim. At \(p=0\), every finite \(L\) chain
eventually reaches \(Z=0\), even when \(R_0>1\); its active state is
quasi-stationary. For \(p>0\), the exact stationary law is

\[
\pi_z=\pi_0\binom Lz
\left(\frac{b}{L\mu}\right)^z
\left(\frac{L\nu p}{b}\right)_z,
\]

where \((x)_z\) is the rising factorial and \(\pi_0\) normalizes the law. In
the supercritical regime, the active-state extinction time has leading
large-\(L\) form

\[
\tau_{\rm ext}=\operatorname{poly}(L)
\exp\left[L\left(\log R_0-1+R_0^{-1}\right)\right].
\]

A single early lineage has birth--death survival probability
\(s=1-R_0^{-1}\). In the rare-immigration limit the active duty fraction is
approximately

\[
\frac{L\nu p\,s\,\tau_{\rm ext}}
{1+L\nu p\,s\,\tau_{\rm ext}}.
\]

At fixed \(L\), \(\lim_{p\downarrow0}\pi_p=\delta_0\), including when
\(R_0>1\). Thus “every \(p>0\)” requires the large-system/quasi-stationary
limit before \(p\downarrow0\), or at least \(p\) not exponentially smaller
than the inverse active lifetime. The finite-size stationary half-occupancy
scale is approximately

\[
p_{1/2}(L)\simeq\frac{1}{L\nu s\tau_{\rm ext}},
\]

which is nonzero at finite \(L\) but exponentially small in a supercritical
large system. A finite neural run never proves the singular limit from one
positive dose.

The exact Poisson-immigration representation of the probability of reaching a
declared macroscopic set by \(T\) is

\[
P(\text{hit by }T)=
1-\exp\left\{-\int_0^T\lambda_p(u)
F_{\rm hit}(T-u)\,du\right\},
\]

where \(\lambda_p\) is the eligible seed intensity and \(F_{\rm hit}\) is the
one-seed hitting-time distribution. In the rare-seed,
\(T\ll\tau_{\rm ext}\) regime, replacing that distribution by a survival
probability \(s\) and a hard macroscopic growth delay
\(t_g\simeq\log L/(b-\mu)\) gives

\[
P(\text{outbreak by }T)
\simeq1-\exp[-L\nu p s(T-t_g)_+],
\qquad
p_{50}(T)\simeq
\frac{\log2}{L\nu s(T-t_g)}.
\]

If an outbreak lowers strict performance by \(\Delta C\), the across-seed mean
has the exponential-looking response

\[
E[C_T(p)]\simeq C_{\rm clean}
-\Delta C\{1-\exp[-L\nu p s(T-t_g)_+]\}.
\]

This gives a precise version of the suspected exponential low-\(p\) effect:
\(p\) changes the waiting-time mixture, while conditional post-onset growth
and plateau are \(p\)-independent. The apparent dose boundary must move as
\(1/[L(T-t_g)]\) in this finite-horizon approximation; it is not a stable
positive \(p_c\). “Ever hit” under perpetual immigration is not itself a phase
diagnostic, because even a subcritical finite chain eventually experiences a
large fluctuation.

For heterogeneous GSM-Infinite neighborhoods, the corresponding linearized
model is

\[
\dot x_i=\nu_i p(1-x_i)
 +(1-x_i)\sum_jB_{ij}x_j-\mu_i x_i.
\]

The clean state loses stability when

\[
\rho\!\left(\operatorname{diag}(\boldsymbol\mu)^{-1}B\right)>1.
\]

The Perron vector predicts which operation--template families should acquire
descendants first. This longitudinal offspring kernel is not the same object
as the instantaneous neutral-tag gradient Gram matrix in Section 6.7. The
immigration vector must also reach the supercritical Perron component; an
unreachable active component does not alter the clean trajectory.

The decisive negative control is fresh re-coining. If every descendant must
receive another verifier error, then \(b(p)=pb_0\), so

\[
R_0(p)=\frac{pb_0}{\mu},\qquad p_c=\frac\mu{b_0}>0.
\]

There is then no generic \(p=0\) discontinuity. Similarly, fixed clean
success \(q>0\), clean replay on the raw clock, or flushing the accepted
lineage memory can remove the absorbing boundary. Evidence for the proposed
mechanism therefore requires all of the following:

- a one-lineage pulse has supercritical survival or mean offspring above one;
- conditional post-onset slopes and plateaus agree across positive \(p\),
  while waiting times scale as \(1/p\);
- switching the defect off after establishment preserves the active state only
  when the proposed replay or transfer memory is retained;
- flushing that memory changes survival without changing the forked policy,
  optimizer state, prompt cursor, or clean verifier;
- seed-level outcomes form the predicted clean/endemic mixture, and the
  inferred boundary moves with \(L\) and horizon as specified above.

Without those tests, finite-run bimodality is only rare seed/no-seed
nucleation, and fitting an exponential curve does not establish a phase
transition.

### 3.12 Iterative-SFT selection has an exact finite critical point

**[HYPOTHESIS—IDEALIZED MAP, 2026-08-09]** Iterative SFT supplies a phase
mechanism that is absent from the current one-pass frozen-bank SFT and ordinary
on-policy RL runs. Let \(x_t\) be the probability that round-\(t\) teacher
sampling emits a reproducible answer-correct/strict-wrong behavior \(A\). For
each raw prompt, draw exactly \(n\) candidates. Each \(A\) candidate passes the
imperfect verifier independently with conditional probability \(p\). Use an
\(A\) target in the next SFT dataset if at least \(h\) accepted \(A\) samples
appear; otherwise use a canonical strict target.

If one fixed-cardinality SFT round exactly reproduces this target mixture, then

\[
x_{t+1}=F_h(x_t;p)
=1-\sum_{j=0}^{h-1}
\binom{n}{j}(px_t)^j(1-px_t)^{n-j}.
\]

For the one-hit rule \(h=1\),

\[
F_1(x;p)=1-(1-px)^n,\qquad F_1'(0;p)=np.
\]

The clean fixed point changes stability at

\[
\boxed{p_c=\frac1n.}
\]

If the measured small-mixture target-to-model transfer gain is \(\chi\), the
local prediction becomes \(p_c=1/(n\chi)\). This is a finite critical point,
not a singularity at perfect verification. Exact zero \(A\) support remains
absorbing even above \(p_c\); any positive support grows when \(np\chi>1\).
A baseline innovation rate, imperfect strict fallback, or finite sampling
rounds the population transition and must be measured rather than ignored.

The requested doses become a sharp diagnostic at \(n=16\):

| Conditional \(p\) | \(np\) | Stable positive fixed point |
| ---: | ---: | ---: |
| 0% | 0.00 | none; \(x_*=0\) |
| 1% | 0.16 | none; \(x_*=0\) |
| 5% | 0.80 | none; \(x_*=0\) |
| 10% | 1.60 | \(x_*=0.670712\) |

At \(n=128\), by contrast, \(p_c=0.78125\%\). The ideal positive fixed points
at 1%, 5%, and 10% are 0.405653, 0.998578, and 0.999999. Thus an iterative
selection experiment with 128 attempts predicts strong 5--10% saturation,
whereas \(n=16\) puts the same grid on opposite sides of the boundary. The
current RL dose sweep does not implement this recurrence, so these values
cannot be used to explain its outcomes post hoc.

A two-hit rule produces a stronger phenomenon:

\[
F_2(x;p)=1-(1-px)^n-npx(1-px)^{n-1}.
\]

Here \(F_2'(0;p)=0\), so the clean state remains stable for every \(p\).
Solving \(F_2(x;p)=x\) and \(F_2'(x;p)=1\) at \(n=128\) gives the saddle-node

\[
\boxed{p_{\rm sn}=0.0260972581,\qquad x_{\rm sn}=0.5399279802.}
\]

Above this point, clean and high-\(A\) states coexist around an unstable basin
separator. At 5%, the separator and high fixed point are 0.064154 and
0.988342; at 10% they are 0.013805 and 0.999979. A cold start can remain clean
while an \(A\)-seeded start converges high at the same verifier quality. This
is a genuine bistable construction. Calling it hysteresis still requires
bidirectional warm/cold initialization or finite innovation: an exactly clean
absorbing state never leaves by itself.

The immutable theory artifact is:

    /checkpoint/ram-h100-2/tianhaowu/rsci/analysis/
    iterative-sft-phase-map-20260809-025607/{summary.json,phase_map.svg}

The JSON, SVG, and analyzer SHA-256 values are respectively
f55f6d25db0a26f9b9c70353a9c008e8e7126fc26c1bf4a74b78232eba8d8f43,
65d0de59500f7fffc07f99c4d2924349985c7ee9882abce6b6db7faa634c3576,
and
92dd75df2b757ca612734bf75a3e9db14f46d437f1a1bc5d6b87bb935b27331a.
Its canonical content SHA-256 is
a193abb077911c177ded5eefc8519c8dbf0b75a3591c8bbde8f8d797dbc9ce2c.
It explicitly marks the result as a theory prediction, not an observation from
the current RL runs.

The cheapest empirical test first estimates \(\chi\) with two small static SFT
mixtures, then uses six fixed-raw iterative rounds at \(n=16\) with
\(p\in\{0,0.01,0.05,0.10\}\). Prompts, candidate request seeds, raw candidate
count, strict fallback targets, training rows, optimizer steps, and evaluation
seeds must be identical across arms. Fixed accepted count is forbidden because
Section 3.6 shows that it cancels the probability intervention. Use a
deterministic shortcut subtype \(A^\star\), not the heterogeneous union of all
strict-wrong answers, and report its lineage separately from total \(A\).
For the two-hit test, use \(n=128\) and compare cold and
forced-\(A^\star\) starts at 1%, 5%, and 10%. At \(n=16\), the corresponding
saddle is 20.387%, so the requested grid is only a subcritical negative
control. A critical estimate is credible only if it moves as \(1/(n\chi)\)
when \(n\) changes and stabilizes with additional rounds.

#### 3.12.1 A natural deterministic lineage: equal-valued parent aliases

**[OBSERVATION—FROZEN FOUR-ARM AUDIT, 2026-08-09]** The source evaluations
contain a concrete task-correlated behavior suitable for an \(A^\star\)
lineage readout. For a canonical child \(c\), let \(G_c\) and \(P_c\) be its
gold and predicted parent sets. A guarded value-alias substitution satisfies

\[
G_c\setminus P_c=\{u\},\qquad
P_c\setminus G_c=\{v\},\qquad
\operatorname{value}(u)=\operatorname{value}(v)
=\widehat{\operatorname{value}}(v),
\]

while the predicted value of \(c\) is correct. The added parent \(v\) must be
a canonical node that is not a descendant of \(c\), and predicted parameter
names and variable letters must each be unique. These guards exclude parser
overwrite artifacts and cyclic pseudo-substitutions.

The acceptance mechanism is exact: replacing semantic parent \(u\) by the
different parent \(v\) does not change the scalar arithmetic when their values
coincide. An answer-only verifier therefore accepts the unchanged final answer,
whereas the dependency-graph verifier observes \(u\ne v\) and rejects it. This
is a task--behavior interaction, not trajectory-independent label noise.

The deterministic audit joins rollouts by task index rather than file order,
replays both released and executable graders, validates the authority and
source self-hashes, and parses the exact bytes whose 140 rollout-file hashes
were checked. Across the four step-4000 policies, 35 operations, and 200
prompts per operation, the intersections with
\(A=\{\text{answer correct, strict wrong}\}\) are:

| Subclass | Rows | All 28,000 | Among 4,901 \(A\) |
| --- | ---: | ---: | ---: |
| Unguarded scalar alias | 654 | 2.336% | 13.344% |
| Guarded acyclic alias | 611 | 2.182% | 12.467% |
| Added parent precedes canonical child | 526 | 1.879% | 10.733% |
| Alias is sole parsed graph defect | 117 | 0.418% | 2.387% |
| Sole graph defect and arithmetic trace clean | 108 | 0.386% | 2.204% |
| Also preceding-parent compatible | 104 | 0.371% | 2.122% |

The last three rows are deliberately distinct. “Pure” means pure under the
parsed dependency graph only; nine of the 117 rows have an additional
executable equality-chain error. Only the 108 trace-clean rows are naturally
isolated examples of the proposed semantic defect. The broader 611-row class
is useful as a lineage marker but cannot support a sole-cause claim when other
reasoning defects co-occur.

The task-side susceptibility is large: 6,610/7,000 prompts (94.429%) have at
least one acyclic equal-valued alternative somewhere in the canonical graph,
and 6,572/7,000 (93.886%) have one declared before the affected child. The
guarded behavior occurs on 454 distinct prompts; 114 prompts recur in at least
two policy arms and nine in all four. Of 574 exact
(prompt, child, omitted parent, added parent) signatures, 99 recur in at least
two arms and six in all four. This recurrence plus the deterministic
arithmetic invariance establishes a real, repeated mechanism; it does not yet
establish that verifier exposure increased its policy probability.

| Difficulty | Guarded alias / \(A\) | Trace-clean graph-pure |
| --- | ---: | ---: |
| OP11--20 | 261 / 2,238 = 11.66% | 96 |
| OP21--40 | 263 / 2,141 = 12.28% | 12 |
| OP41--45 | 87 / 522 = 16.67% | 0 |

Thus the alias family persists on the hardest tasks, while naturally isolated
instances disappear because hard trajectories contain additional defects.
Across p00, p01, p05, and p10 the guarded counts are respectively 135, 155,
179, and 142 out of 7,000. This non-monotone cross-policy comparison is not a
dose effect: the policies have different training histories and source
exposures.

A trace-clean graph-pure example is p00/OP12/task 34, rollout
79353c13038543eba2aa7675920b5aa5. The gold derivation uses
“total number of schools in Ruby Bay = 4” as a parent of
“private middle school in Riverton City”; the model instead uses
“total number of schools in Clearwater Bay = 4”. The child and final answer
remain 24. Node names, node values, the arithmetic trace, and every other edge
match; answer reward is one and strict graph reward is zero.

The immutable artifact is:

    /checkpoint/ram-h100-2/tianhaowu/rsci/analysis/
    value-alias-shortcut-audit-20260809-033930/summary.json

Its file and canonical-content SHA-256 values are
7c0fab39c1c1520598099572da59914a9298693e565a71695decbbf99fc43fc8 and
a78df658c295a036366be2cf9a774623f4775db311dab6a98b13b68dea89c13b.
The analyzer, alias parser, released graph parser, and executable grader
SHA-256 values are respectively
16fbb559eecd35ff78c008f1b8ffd62a91a0c8a86c4549348afb3989e50772b7,
5d852e20dc5356de21e685d87a3b19fb6f8d1a855734e556e74dbea8761cd31a,
36112fc62c100b721ef287464a50e6d01d4b386094f5d94219b93892d912e5a0,
and 06afc954eff1a203f4d914e36536b7f0ba892d0d3f70daaf42e5090c272d083c.
An independent temporary rerun was byte-identical to the preserved artifact.

This observation changes the next intervention, not the current causal
conclusion. Construct \(A^\star\) by applying one validated equal-value parent
substitution to an otherwise canonical strict completion, then assert answer
correctness, exactly one graph mismatch, and zero independent executable
issues. Never train directly on the heterogeneous 611 natural rows. The
iterative-SFT phase test can then measure both exact synthetic \(A^\star\) and
the broader natural lineage, with identical raw candidate clocks and prompt
seeds across verifier-probability arms.

### 3.13 Quenched semantic blind spots predict a Griffiths regime

**[HYPOTHESIS—PRIOR RARE-REGION MATH, NEW VERIFIER MAPPING, 2026-08-09]**
Fresh trajectory coins are annealed disorder: every generation sees another
independent draw. A task-specific blind spot is quenched disorder. Let
\(z_i\in\{0,1\}\) permanently mark semantic neighborhood \(i\) as vulnerable
and linearize its \(A\) amplitude as

\[
\dot{\mathbf x}
=\left[B-\operatorname{diag}(\boldsymbol\mu)
+a\operatorname{diag}(\mathbf z)\right]\mathbf x
+O(\|\mathbf x\|^2).
\]

If \(B\) is local, the bulk can remain subcritical while a rare contiguous
vulnerable region of size \(\ell\) is locally supercritical. Suppose its
occurrence probability and lifetime scale as

\[
w_\ell\asymp e^{-c(p)\ell},
\qquad
\tau_\ell\asymp e^{s\ell}.
\]

Regions with \(\tau_\ell>t\) then give the rare-region tail

\[
m(t)\asymp
\int_{\log(t)/s}^{\infty}e^{-c(p)\ell}\,d\ell
\propto t^{-c(p)/s}.
\]

Thus a clean gapped system can relax exponentially at \(p=0\), while every
positive density of persistent blind spots produces a non-universal algebraic
tail over a Griffiths interval. This is a qualitative perfect-versus-imperfect
dynamical distinction even when the infinite-time stationary \(A\) density is
still zero. It is not by itself a different strict-performance ceiling.

Finite size is decisive. Among \(L\) neighborhoods,
\(\ell_{\max}\sim\log L/c(p)\), so the apparent algebraic regime ends near

\[
t_{\max}(L)\sim L^{s/c(p)}.
\]

A power law at one tuned dose is insufficient. The required signatures are:
continuously varying decay exponents over a dose interval; a cutoff that grows
as a power of \(L\); heavy-tailed extinction times with a persistent
mean/median gap; activity localized on the same fixed vulnerable regions; and
different outcomes for contiguous and permuted masks with identical counts.
An annealed control must return to exponential relaxation away from its single
bulk critical point.

The hypothesis fails immediately when parameter transfer is dense and
delocalized. For a normalized response eigenvector \(v\), report

\[
\operatorname{IPR}(v)=\frac{\sum_i v_i^4}{(\sum_i v_i^2)^2}.
\]

Localized rare modes keep \(O(1)\) IPR as \(L\) grows; a shared mode has
IPR \(O(1/L)\). The existing six-neutral-tag gradient kernel is almost rank
one and its top-mode mass is nearly uniform, so it argues against using those
artificial tags as rare regions. It does not settle the unmeasured
operation--template transfer kernel.

GSM-Infinite already permits a clean, config-only correlation-length screen.
The OP10--40 source has 93 balanced operation--template strata, each with
333--334 rows. Set the global false-positive rate to zero, set one selected
operation's override to \(1/3\), and use a deterministic template gate of
probability \(1/3\). Within that one semantic stratum the conditional rate is
\((1/3)/(1/3)=1\), so every valid \(A\) candidate is accepted; the other 92
strata are clean. This is exactly about \(1/93=1.075\%\) task coverage, though
its candidate-weighted FPR need not equal \(1/93\).

The matched three-way screen is:

1. iid sample-slot defects at nominal rate \(1/93\);
2. random prompt-group blind spots with gate probability \(1/93\) and
   conditional rate one;
3. one deterministic operation--template blind spot with task coverage
   \(1/93\).

The second and third arms match all-or-none group burstiness while changing
semantic correlation length. Exact realized candidate mass, trigger count,
mixed-group count, raw exposure, and optimizer updates must be reported; a
shuffled-recipient control is needed if semantic candidate prevalence differs.
Selecting 1, 5, or 9 strata gives approximately 1.08%, 5.38%, or 9.68% task
coverage, but a broad sweep is justified only after a forced-pulse kernel shows
localized transfer. The current attempt analyzer rejects nonempty per-operation
rates, so its replay contract must be extended before any launch. No such job
has been submitted.

This static construction is a quenched verifier blind spot, not an autonomous
lineage. Dynamic lineage state must not live inside the environment: the
current RL runtime has multiple asynchronous workers and does not checkpoint
environment-local memory. A genuine retained-lineage experiment must use an
explicit immutable iterative-SFT replay ledger, as in Section 6.8.

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

At the raw-exposure clock, the \(1\%\) arm had 1.664 times as many optimizer
updates as clean and appeared better; at the optimizer clock, it appeared
worse. This reversal shows that the apparent benefit is not invariant to the
training clock and is consistent with update-throughput imbalance. With one
run per arm, it does not identify optimizer-update count as the causal mediator
or show that corrupted updates generalize better. The \(5\%\) arm remains
worse under either clock at these windows.

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

### 4.4 Live main-run paired-clock follow-up

**[OBSERVATION—CURRENT; PRELIMINARY]** The paired live artifact is

```text
/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/
verifier-defect-main-v2-live/paired_clocks.json
```

with SHA-256
`b5c0a2797a3d49b04ca8d8c6112e88a045fedb46b8cba3a29ace9059cd6d9f45`.
Its implementation SHA-256 is
`8f31ad46baecbff6ceaaff2584f45735601d641fd3dbb9d6fe534a922b79c61c`.
For every selected checkpoint it verifies 200 strict binary rows for each of
OP11–45, pairs exact prompt index and text across arms, and hash-binds every
input shard. The training experiment still has only one run per arm.

The sustained OP15–17 summaries are:

| Clock and statistic | \(p=0\) | \(p=1\%\) | \(p=5\%\) |
| --- | ---: | ---: | ---: |
| Optimizer-step AUC through step 1,600 | 10.3438% | 9.5456% | 5.1458% |
| Mean of steps 1,500–1,600, five evaluations | 16.10% | 15.10% | 10.70% |
| Raw-exposure AUC through \(E^*=1{,}386{,}496\) | 8.1420% | 10.2427% | 8.0333% |

Thus the \(1\%\) arm is \(-0.7982\) pp versus clean on per-update AUC but
\(+2.1007\) pp on per-raw-exposure AUC. The \(5\%\) arm is \(-5.1979\) pp per
update and \(-0.1087\) pp per raw exposure. The nearest raw-exposure endpoints
were step 1,325 / 1,396,736 for clean, step 2,075 / 1,388,032 for \(1\%\), and
step 2,500 / 1,386,496 for \(5\%\); their maximum target mismatch was 0.739%.
The apparent low-dose advantage is present only under the raw-exposure AUC in
this window and disappears under the optimizer-step estimand. This is
consistent with a clock/throughput contribution, but the one-run comparison
does not identify that contribution causally and provides no evidence that
corrupted updates generalize better.

The step-1,600 endpoint alone is misleading: \(1\%\) was +1.17 pp on OP15–17,
but its AUC and last-five-evaluation mean were both below clean. Endpoint
bootstrap intervals and McNemar tests condition on the realized trained
policies. They quantify prompt-level evaluation uncertainty only; with one
training run per arm, they are not treatment-effect confidence intervals or
significance tests.

Every one of the six selected arm/checkpoint evaluations had all 35 operation
shards mixed across policy versions \([\text{step}-1,\text{step},\text{step}+1]\).
The logged `Policy v` field is only the minimum of that set, not a row-level
version histogram. The comparisons are consequently between adjacent-policy
mixtures. Finally, all arms scored exactly 0/1,000 on unseen OP41–45 at both
clocks, so this prefix contains no evidence about the requested hard
generalization ceiling.

**[OBSERVATION—LATER IMMUTABLE REFRESH, 2026-08-07]** The same conclusion
survives a longer common window. The frozen refresh artifacts are

```text
/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/
verifier-defect-main-v2-clock2100-refresh-20260807/{summary.json,paired_clocks.json}
```

with SHA-256 values
`9fe7aa01bb866b31c19de5857bdbc1fb9682cef79799e9b51fdcd9cbb64ae56e`
and
`ff9e0bf10edebdb1b27f7c201bda209a8353edbfb87078dfa4097adbf493d9e2`.
The paired raw-exposure curve is `summary.svg` in the same directory (SHA-256
`476f416b2c0d93c4f274afb3f6fd31c5306ed9dd802cf4b5861947add2462868`).
The selected common clocks are optimizer step 2,100 and nearest raw exposure
`E*=1,780,736`.

| Clock and OP15–17 statistic | `p=0` | `p=1%` | `p=5%` |
| --- | ---: | ---: | ---: |
| Optimizer-step AUC through 2,100 | 11.9683% | 10.9911% | 7.0129% |
| Mean of the last five evaluations through 2,100 | 17.13% | 16.43% | 14.27% |
| Step-2,100 endpoint | 17.00% | 15.83% | 15.50% |
| Raw-exposure AUC through `E*` | 9.9283% | 11.6049% | 9.3022% |
| Nearest-`E*` endpoint | 18.17% | 17.83% | 18.83% |

The `1%` contrast is `-0.9772` pp by optimizer-step AUC but `+1.6766` pp by
raw-exposure AUC. The `5%` arm is `-4.9554` pp per-update AUC and `-0.6261`
pp per-raw-exposure AUC. Its raw-clock endpoint happens to exceed clean by
0.67 pp despite the worse full-window AUC, a direct example of why one endpoint
must not replace the curve. At the matched optimizer endpoint, OP21–40 strict
pass@1 is 0.75% / 0.425% / 0.00%; at the nearest raw-exposure endpoint it is
0.60% / 1.00% / 0.80%. Every arm remains exactly 0/1,000 on OP41–45 at both
clocks.

The nearest raw evaluations occur at steps 1,800 / 2,750 / 3,250 with exposure
1,782,784 / 1,780,736 / 1,787,008, a maximum target deviation of 0.352%.
Every selected optimizer- and raw-clock evaluation mixes adjacent policy
versions on all 35 operations. Prompt tests and bootstrap intervals therefore
remain conditional diagnostics, not training-treatment inference. This
snapshot was taken while all three jobs were healthy and running; it is a
longer prefix, not a final-ceiling result.

**[OBSERVATION—LONGER IMMUTABLE REFRESH, 2026-08-07]** At common optimizer
step 2,550 and raw-exposure target `E^*=2,026,752`, the same sustained result
persists. The frozen artifacts are

```text
/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/
verifier-defect-main-v2-clock2550-refresh-20260807/
{summary.json,paired_clocks.json,summary.svg}
```

with SHA-256 values
`6a54d336b266807c1cfd428cd615e567da016e1123f38a631155c458dd474878`,
`2fcb79884a8ca8161ba12aba6b30f32877aca0cea045abf50e121a7c1047f76f`,
and
`dd4006f55a386e845f0f67714d9ada413a34c1e607227d0dcadcdcb32a81f9ba`.

| Clock and OP15--17 statistic | `p=0` | `p=1%` | `p=5%` |
| --- | ---: | ---: | ---: |
| Optimizer-step AUC through 2,550 | 12.8627% | 11.9101% | 8.2312% |
| Mean of the last five common evaluations | 16.37% | 16.37% | 12.60% |
| Step-2,550 endpoint | 16.33% | 16.67% | 12.50% |
| Raw-exposure AUC through `E^*` | 10.8603% | 12.0269% | 9.9498% |
| Nearest-`E^*` endpoint | 18.00% | 9.33% | 13.00% |

The 1% contrast remains negative per optimizer-step AUC at -0.9526 pp and
positive per-raw-exposure AUC at +1.1665 pp. The 5% contrasts are -4.6315 pp
and -0.9105 pp. Yet the 1% nearest-raw endpoint is now 8.67 pp below clean,
despite its better full-window raw AUC; at the prior raw snapshot it was only
0.33 pp below. The 5% endpoint also changed from 0.67 pp above clean to 5.00 pp
below. This is not a contradiction: it is direct evidence that the individual
evaluation endpoint is high variance and cannot substitute for the curve.

The nearest raw evaluations are steps 2,125 / 3,175 / 3,700 with exposures
2,036,608 / 2,032,512 / 2,026,752, at most 0.486% from the target. At matched
step, OP21--40 strict pass@1 is 1.000% / 0.725% / 0.125%; at the nearest raw
clock it is 0.775% / 0.425% / 0.825%. OP41--45 remains exactly 0/1,000 for
every arm at both clocks. All six selected evaluations again mix adjacent
policy versions on all 35 operations. This longer one-seed prefix strengthens
the clock and endpoint diagnosis, but still contains no hard-ceiling or
phase-transition evidence.

**[OBSERVATION—STEP-2,625 IMMUTABLE REFRESH, 2026-08-07]** A further frozen
refresh at common optimizer step 2,625 and raw-exposure target 2,120,832 is in

```text
/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/
verifier-defect-main-v2-clock2625-refresh-20260807/
{summary.json,paired_clocks.json,summary.svg}
```

with SHA-256 values
`0525acd4bf86f2394db841afd2e452f6f6579dd44edf1a3a30f044936a2146b1`,
`a34d44a3015918510f1e85fe02e390f3d531e6cca7f37e6d3d22c2bbd560d946`,
and
`a82e4f6408b2c0dce1e57478bce88d2044c3c0488efb696592147f3719cbf029`.
Optimizer-step OP15--17 AUC is 12.9897% / 12.0437% / 8.3683% for
0% / 1% / 5%, contrasts -0.9460 and -4.6214 pp. At the raw clock it is
11.1815% / 12.1070% / 10.1185%, contrasts +0.9254 and -1.0631 pp. Thus the
low-dose clock reversal persists while the high dose remains worse on both
curve summaries.

The last-five optimizer means are 17.23% / 16.37% / 13.20%; the step-2,625
endpoints are 17.17% / 17.50% / 14.33%. The nearest raw endpoints are 16.50% /
16.67% / 14.00% at steps 2,225 / 3,325 / 3,875 and exposures 2,110,080 /
2,120,832 / 2,122,496, at most 0.507% from target. OP21--40 is 0.925% / 0.700% /
0.200% at the optimizer clock and 0.800% / 1.075% / 0.675% at the raw clock;
OP41--45 is again exactly zero. Every selected evaluation mixes adjacent
policy versions. The transient +0.33 pp 1% optimizer endpoint coexists with a
negative full-window AUC and therefore strengthens, rather than weakens, the
endpoint-variance diagnosis.

**[OBSERVATION—STEP-4,000 DESCRIPTIVE REFRESH, 2026-08-07]** Once the clean
arm crossed step 4,000, a further hash-bound snapshot was frozen at

```text
/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/
verifier-defect-main-v2-clock4000-refresh-20260807/
{summary.json,paired_clocks.json,summary.svg}
```

with SHA-256 values
`2a9e860e2d601ff2a191341c67a9738c1523f34e31fb6d1d4670f662e3366215`,
`e03ba77e948493e8e027f435168493c5b3ef635361358c0bfdb38575353dd842`,
and
`74e6fc9b10acac746eb00c2f1b3774cc2240c29374356d4faf506f6d2b9c2ae6`.
The OP15--17 curve summaries are:

| Clock and statistic | `p=0` | `p=1%` | `p=5%` |
| --- | ---: | ---: | ---: |
| Optimizer-step AUC through 4,000 | 14.5880% | 13.3370% | 10.3969% |
| Mean at steps 3,900/3,925/3,950/3,975/4,000 | 20.73% | 16.27% | 15.47% |
| Step-4,000 endpoint | 20.83% | 12.83% | 14.67% |
| Raw-exposure AUC through `E*=3,175,552` | 13.0526% | 12.9639% | 12.3249% |
| Nearest-`E*` endpoint | 15.00% | 13.50% | 17.67% |

The 1% contrast is now -1.2510 pp per optimizer-step AUC and -0.0886 pp per
raw-exposure AUC. The earlier positive raw-budget contrast has therefore
decayed to essentially zero and changed sign. The 5% contrasts remain
negative at -4.1911 and -0.7277 pp. Its +2.67 pp nearest-raw endpoint again
coexists with a worse full-window curve, so it is not evidence of a late
high-dose benefit.

The nearest raw checkpoints are steps 3,525 / 5,125 / 5,825 with exposures
3,171,072 / 3,178,240 / 3,175,552, at most 0.1411% from the target. OP21--40
strict pass@1 is 1.25% / 1.00% / 0.65% at matched optimizer step and 1.175% /
1.325% / 1.05% at the raw clock. OP41--45 remains exactly 0/1,000 for every
arm at both clocks. All selected OP11--40 evaluations remain adjacent-policy
mixtures; the p=5% step-4,000 OP41--45 shards are the non-mixed exception and
still score zero.

The artifacts explicitly set `artifact_audit_valid=false`,
`causal_claim_valid=false`, and `phase_transition_claim_valid=false`: the
legacy V2 runs lack exact attempt-ledger provenance, the raw clock is a
periodic finalized-group proxy, and there is still one training run per arm.
The prompt bootstrap and McNemar values condition on these realized policies
and are not treatment-effect inference. The longer snapshot strengthens the
throughput/transient interpretation; it still says nothing about a nonzero
unseen-hard ceiling.

#### Four-arm composition at the withdrawal source state

**[OBSERVATION—CURRENT; DESCRIPTIVE]** A separate immutable artifact adds the
10% arm and records the exact \(S/A/W\) composition at the step-4,000 state
from which the withdrawal screen forks:

```text
/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/
verifier-defect-source-step4000-four-arm-20260809-022824/summary.json
```

Its file SHA-256 is
`3218375c550a3cb2ac0d502f04a1b2e690acc38273ec5fdf6686e39bbae8d404`;
its canonical content SHA-256 is
`b5eee4de51b20b5616b27cbc9c212fc15fbc88c6505abbf805ac91414c0233a5`.
The analyzer SHA-256 is
`39fe4a55ffbf413ab943f6c4a46a7dd0b74044a699ead7f20f69f243791e7170`.
It validates 140 input shards, 200 rows per operation, exact prompt identity
across arms, clean strict evaluation reward, binary \(S/A/W\) partitioning,
and the logged policy-version mixture for each operation.

| Step-4,000 rate | \(p=0\) | \(p=1\%\) | \(p=5\%\) | \(p=10\%\) |
| --- | ---: | ---: | ---: | ---: |
| OP21--40 strict \(S\) | 1.250% | 1.000% | 0.650% | 0.275% |
| OP21--40 strict-wrong \(A\) | 11.175% | 12.800% | 15.075% | 14.475% |
| OP21--40 answer correct \(S+A\) | 12.425% | 13.800% | 15.725% | 14.750% |
| OP41--45 strict \(S\) | 0.000% | 0.000% | 0.000% | 0.000% |
| OP41--45 strict-wrong \(A\) | 9.400% | 11.400% | 16.900% | 14.500% |
| OP15--20 strict \(S\) | 14.833% | 9.083% | 9.583% | 9.250% |
| OP15--20 strict-wrong \(A\) | 27.667% | 25.917% | 26.417% | 24.333% |

The task dependence is more informative than a single aggregate score. On
hard OP21--40, defect dose substitutes \(A\) behavior for strict reasoning:
strict success falls nearly monotonically, while \(A\) and final-answer
success rise through 5% and bend down at 10%. On the easier bridge OP15--20,
both strict and total answer performance are below control, and \(A\) does not
grow. On unseen OP41--45, the defect increases final-answer-only success but
never produces one strict success. This is verifier-induced behavior and
curriculum rotation, not strict generalization.

The 5--10% bend is compatible with the smooth group-activation saturation
\(1-(1-p)^C\) plus destructive proxy-only updates. It is not a \(p=0\)
singularity: there is no jump isolated at the first positive dose, no seed
replication, and no pure-policy evaluation. A later common-step-7,625 check
finds OP21--40 \(A\) rates of 12.000%, 13.700%, 15.125%, and 14.775%;
the paired p10-minus-p5 contrast is only -0.35 pp, with a policy-conditional
two-sided exact \(p\)-value of 0.636. It does not turn the source-state bend
into a discontinuity.

Late matched-step comparisons also cease to share a fresh-data history. The
31,000-row source has no one-epoch guard. The first evaluation whose periodic
finalized-group proxy crosses 31,000 is step 4,525 / 6,475 / 7,300 / 7,375 for
p0 / p1 / p5 / p10, respectively. These are conservative guaranteed-by
checkpoints, not exact cursor-wrap times: in-flight and dropped groups can make
the true cursor wrap earlier. Thus step 7,625 compares different repetition
histories as well as different raw exposure. The withdrawal continuation's
fresh no-wrap pool is essential, not merely an efficiency choice.

Finally, the p0, p1, and p10 step-4,000 evaluations mix versions
3,999--4,001 on all 35 operations; p5 mixes versions 3,999--4,000
on OP11--40 and is pure version 4,000 only on OP41--45. Accordingly, the
artifact sets both `causal_claim_valid` and `phase_transition_claim_valid` to
false. The sealed standalone source evaluation and withdrawal intervention
are required to distinguish persistent dynamics from this cross-sectional
dose response.

### 4.5 Mechanism audit: why a small \(p\) changes the training clock

**[OBSERVATION—CURRENT]** The immutable threshold audit through saved shipped
step 899 reconstructs the following cohort mechanism:

| Arm | All defect-only groups | OP21–40 defect-only groups | OP21–40 activation among eligible zero-strict groups | Mean operation among mixed-proxy groups | OP15–20 strict-row rate, early → late |
| --- | ---: | ---: | ---: | ---: | ---: |
| \(p=0\) | 0 | 0 | 0.0% | 12.631 | 1.037% → 12.688% |
| \(p=1\%\) | 579 | 393 | 35.566% | 18.410 | 0.007% → 7.654% |
| \(p=5\%\) | 1,086 | 756 | 67.864% | 22.036 | 0.000% → 1.982% |

The exact intervention-to-cohort chain is:

1. A persistent hash draw changes an answer-correct, strict-wrong trajectory
   from proxy reward 0 to 1 with probability \(p\).
2. In a group with \(m\) such candidates and no strict positive, the chance of
   at least one proxy positive is \(1-(1-p)^m\). The exact chance of a mixed
   reward vector subtracts \(p^{128}\) when \(m=128\), because an all-triggered
   group is homogeneous positive; no such group occurred in this audit.
3. Because candidates persist on hard operations, increasing \(p\) rotates the
   shipped mixed-proxy curriculum toward harder prompts while assigning
   positive advantage to strict-wrong recipients.
4. The extra activated groups increase optimizer updates per raw rollout. At
   low dose this can improve a raw-budget curve through additional updates; at
   higher dose proxy-only hard groups dominate and strict bridge conversion is
   slower.

Writing \(m\approx Kh\) for group size \(K=128\) and candidate rate \(h\), the
activation law is approximately

\[
1-(1-hp)^{128}\approx 1-e^{-128hp}.
\]

This is the sharp small-dose response suspected at the start of the study: the
group multiplier makes \(1\%\) a macroscopic intervention whenever \(128h\) is
not small. For finite \(K\) it is smooth and analytic. Its crossover scale is
\(p\sim 1/(Kh)\), so it is not evidence that final performance has an
exponential singularity at \(p=0\).

An exact replay of the heterogeneous candidate count \(C_g\) sharpens this
claim. The source artifact has SHA-256
`263f20da309fdccc5f1a9916519ba6b4575f0183ea3f64c6e2a4991aedd770ea`.
For each retained strict-zero candidate group, the unconditioned hash law
predicts
\(q_g=1-(1-p)^{C_g}-\mathbf 1[C_g=128]p^{C_g}\) for mixed activation. The
hard OP21--40 cohort gives:

| Arm | Eligible groups | Candidate `C` mean / min,Q1,median,Q3,max | \(\sum_g q_g\) | Observed active | Rate residual |
| --- | ---: | --- | ---: | ---: | ---: |
| `p=1%` | 1,105 | 37.08 / 1, 8, 24, 57, 128 | 300.273 | 393 | +8.392 pp |
| `p=5%` | 1,114 | 40.04 / 1, 9, 29, 65, 128 | 735.218 | 756 | +1.866 pp |

Every stored candidate draw is threshold-consistent with its stored trigger,
and every retained group's mixed-activation flag is consistent with those
draws. This validates application of the frozen draws but does not
independently rederive the legacy hash. The positive residual is consistent
with survivor conditioning because the legacy artifact contains saved,
shipped optimizer cohorts and omits attempted zero-trainable groups; those
missing attempts prevent unique attribution. The residual enrichment is
larger at 1% than at 5%. For 1%, the expected/observed hard-activation pairs are
28.72%/41.84% in steps 0--299, 27.90%/35.21% in 300--599, and 24.76%/29.05%
in 600--899. The analogous 5% pairs are 63.28%/64.72%, 67.21%/70.45%, and
67.55%/68.57%.

Candidate heterogeneity is also quantitatively important. Within the hard
cohort, replacing each \(C_g\) with the cohort mean would predict 31.11%
rather than the exact 27.17% activation at 1%, and 87.17% rather than 66.00%
at 5%. Consequently neither a
mean-candidate approximation nor an "effective FPR" fitted from shipped
groups identifies the injected probability. The known-cost study's immutable
attempt ledger and zero-trainable accounting are required to estimate the
unconditioned activation rate and hazard over attempted groups.

The audit establishes the reward-to-activation and activation-to-curriculum
path for the realized saved cohorts. It does not isolate whether downstream
model changes came from the recipient behavior, the harder prompt allocation,
or merely the extra update count. That is exactly the B/S/G/I decomposition
performed by the fixed-clock SFT experiment below.

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

### 5.2 B/S/G/\(G^\star\)/I recipient design

**[PREREGISTERED]** Doses are \(p\in\{0.25\%,0.5\%,1\%\}\), with deterministic
selection seeds 20260805, 20260806, and 20260807. Hash draws use exact uint64
integer comparisons, not floating-point thresholds.

| Arm | Recipient rule | What it preserves | What it breaks |
| --- | --- | --- | --- |
| **B: behavior** | Promote \(A=\) answer-correct/strict-wrong rows whose defect draw is below \(p\) | Actual behavior-conditioned defect | Nothing; this is the treatment |
| **S: within-prompt shuffled** | For each prompt group, assign exactly B's realized count to independently ranked strict negatives | Hard-sample count, prompt/group allocation, per-group extra-positive histogram | Association between the reward and the particular B recipient |
| **G: global count-matched** | Select exactly B's total count by independent global ranks over strict negatives in the same observed prefix | Total hard-sample count and cutoff | Recipient identity and prompt/group allocation |
| **\(G^\star\): composition-matched global** | Select S's exact candidate-A and noncandidate counts using independent class-specific global ranks in the same prefix | Total count, candidate composition, cutoff | Prompt/group allocation and within-class trajectory identity while retaining the marginal behavior-class mix |
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
S-G &: \text{total within-group versus global allocation mechanism at fixed count},\\
S-G^\star &: \text{allocation at fixed count and coarse behavior-class composition},\\
B-G &: \text{total behavior-targeting effect at fixed count},\\
I-C0 &: \text{class-conditional iid channel plus its selection/optimizer effects}.
\end{aligned}
\]

Any B-versus-I contrast is secondary and must report realized recipient count,
candidate overlap, group count, and raw prefix.

**[OBSERVATION—PRETRAINING MANIPULATION AUDIT]** The byte-pinned arm index
already identifies an important first stage. Across the 15 canonical specs,
S assigns 52.93%–57.23% of its rewards to behavior candidates, versus 100% for
B and 9.96%–14.06% for uniform G. Thus B–S is a partial 42.77–47.07 point
alignment reduction, not behavior versus zero behavior. S–G changes prompt
allocation *and* the candidate/noncandidate recipient mix by 38.87–47.27
points. It is a valid total allocation-mechanism contrast but cannot by itself
identify a prompt-only pathway.

A stratified global control \(G^\star\) can match S's exact candidate and
noncandidate recipient counts while selecting each class by independent global
ranks. Frozen-bank capacity exceeds every candidate quota by at least 174-fold
and every noncandidate quota by at least 1,634-fold, so this control is exactly
feasible. \(S-G^\star\) identifies allocation at fixed marginal behavior class;
\(S-G\) retains the total effect. Because \(G^\star\) intentionally samples
behavior candidates more heavily, it must never be called iid or
behavior-independent.

**[RESULT—INTEGRITY ONLY; SUBMITTED, NO PERFORMANCE OUTCOME]** The additive
extension contains 15 canonical arms: nine fixed-M cells and the six non-alias
fixed-raw cells. Its production build is pinned to source commit
`204c38b662ea561a931c2a881ce9857108d8d818` and reproduced every S quota
exactly. It found candidate capacities of 50,767--209,500 and noncandidate
capacities of 383,281--1,548,811, introduced no new trainability exclusions,
and had maximum rendered length 1,718 tokens. The immutable arm index is

```text
/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect/
frozen-base-op10-12-op15-40-r128-v1/
fixed-clock-sft-v3-extension-gstar-v1/arm_index.json
```

with SHA-256
`9506e6b59749d44f486b115b09e1348d51326d6d6a7bdced57092e337d052130`.
The launch manifest and protected submission ledger have SHA-256 values
`bd6bd81582f0b91755619c2d182ef5daceb243fe336639478160c17e3f97b542`
and
`d627329e70adb12331bec2cf4afbb348644f932d9019575a45b339e77d2c581a`.
All 15 non-exclusive one-H100 jobs were submitted through the control tmux as
Slurm jobs `10269722`--`10269736`; the immutable ledger validates all 15
receipts. At 2026-08-07 12:41:49 UTC every job was pending under `Priority`,
behind the original 55-arm screen, and no trainer log existed.
At 2026-08-07 13:21:32 UTC all 15 were still pending under `Priority`; this is
a soft scheduler ordering, not a dependency on the original screen. Persistent
CPU watcher job `10271222` has an `afterany` dependency on exactly those 15 job
IDs. When released, it verifies the pinned 21-task evaluation snapshot and
atomically writes `watcher/readiness.json`; it does not submit the evaluator.

The separately pinned strict evaluator declares 21 readouts: step 64 for all 15
arms plus one distinct final checkpoint for each of six fixed-raw arms. Its
OP11--45 manifest has SHA-256
`723de5cc0df7dcb441d89b51d720bcd8796ce2f537b5757bdb8b609e6cb4843d`
and specifies 147,000 strict generations. The bound analysis registry has
SHA-256
`867b9ea34c600d751396b2ab2965e865ab9cd02b147f8e8ffdaa847eef66d652`.
Protected evaluation submission was dry-run only: 0 checkpoints were stable,
21 were missing, and no submission intent or GPU array was created.

The index contains 55 distinct canonical training arms: C0, 45 B/S/G arms,
and 9 fixed-raw I arms. It additionally contains 9 byte-identical minimum-dose
fixed-raw aliases of fixed-M B/S/G, for 64 index entries total. Aliases are not
submitted as separate training jobs. \(G^\star\) is a separate additive
15-arm extension and never rewrites this v2 index or launch ledger.

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

**[PREREGISTERED ANALYSIS AMENDMENT—BEFORE OUTCOMES]** The deterministic
fixed-clock analyzer uses 2,000 paired prompt-bootstrap replicates with seed
20260807, resampling within operation with the same draw for every arm and
selection seed. Dose is analyzed on a centered log2 scale, so the three-dose
slope is one half of the high-minus-low difference; adjacent differences and
second-difference curvature are retained. Across the three selection seeds,
two-sided exhaustive sign-flip screens are reported, with Holm adjustment for
the two primary B-band clock-by-dose interactions and separately across all exploratory
assignment/band interactions. No equivalence margin was preregistered, so a
nonsignificant fixed-M slope means no detected reproducible ordering, not proof
of cancellation. The minimum-dose fixed-raw B/S/G view is explicitly an alias,
and the mixed common/final approximately-two-pass curve is reported separately
from both common-step and distinct-final analyses. The \(I-C0\) contrast is
defined only at common step 64: report every I seed/dose against the single C0,
plus descriptive mean, standard deviation, range, and a paired-prompt interval
that includes C0 once. C0 must not be cloned into three control replicates, and
no seed-level sign-flip or Holm test is permitted for \(I-C0\). The physical I
distinct-final dose curve is absolute and descriptive because C0 has no matched
final readout and its steps and example exposures differ. B/S/G allocation
diagnostics must verify B=S prompt/group histograms and report S-versus-G
operation, prompt-group, and behavior-recipient differences before an H3
mechanism claim. A coarse-A-status-matched allocation claim additionally
requires the stratified \(G^\star\) control; prompt allocation alone remains
unidentified because rows can still differ within the A/non-A strata.

All prompt-bootstrap intervals are pointwise, model-conditional, and
non-simultaneous. B/S/G sign-flip p-values are tiny-\(n\) reproducibility screens
conditional on independent symmetric seed effects, not randomized-treatment
inference: with three seeds the two-sided floor is 0.25 and the two-test Holm
floor is 0.5. Component fixed-M and fixed-raw slope p-values are unadjusted;
Holm correction applies only to the declared interaction families.

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

- Supported only by a consistent paired \(B-S\) difference together with its
  audited 42.77–47.07 point first stage.
- A null three-seed B–S screen is inconclusive rather than a falsification,
  because S still rewards the target behavior on roughly 53%–57% of rows. A
  B-versus-C0 difference is insufficient because hard support and prompt
  allocation both change.

**H3: curriculum allocation.** S differs from G because the behavior trigger
chooses which prompts/groups enter training even after recipients are shuffled.

- Uniform \(S-G\) is the total allocation-mechanism effect and includes the
  measured recipient-mix pathway.
- \(S-G^\star\), together with measured operation/prompt differences, tests
  allocation at exactly matched coarse A/non-A counts. It is not a pure
  prompt-allocation contrast: within each class, trajectory identity, length,
  likelihood, and other content can still differ. A null uniform S–G contrast
  does not separately falsify that pathway.

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
3. Every B/S/G paired arm has exact hard-recipient cardinality, B/S has an
   identical prompt-group count histogram, and every \(G^\star\) arm exactly
   reproduces S's candidate-A/noncandidate quotas.
4. G is globally rank-selected only from observed strict negatives;
   \(G^\star\) uses independent domain-separated global ranks for its two
   declared classes; I obeys its exact Bernoulli threshold for every recipient.
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
with scheduler interleaving. At the 2026-08-07 07:55:57 UTC audit, all 55
remained pending: 23 under `QOSGrpGRES` and 32 under `Priority`. There were zero
running, completed, failed, or cancelled jobs, zero training logs or checkpoint
directories, and zero `STABLE` markers, so no SFT performance result existed.
At the 2026-08-07 11:00 UTC refresh, all 55 still remained pending (25
`QOSGrpGRES`, 30 `Priority`); no SFT outcome had appeared.
The 13:21:32 UTC scheduler refresh was unchanged. Watcher job `10261897`
remained pending on its exact 55-job `afterany` dependency.

The strict evaluator is independently pinned to commit
`6e5162658990463fa1c742781b54c71a2a380377`. Its launch manifest has SHA-256
`5e49478b1aef3cb324290dc1f3b8867bad65f386e3814a82ba816f1b499eca6c`
and declares 82 tasks, 7,000 prompts per task, and 574,000 total generations.
Dry submission correctly reported 0 stable and 82 missing checkpoints; the
07:55:57 audit found the same guarded state. No evaluation array or immutable
submission intent was created.

Persistent CPU watcher job `10261897` was then submitted through the protected
control tmux with an `afterany` dependency on all 55 unique training job IDs.
It is pending on that dependency under `cpu_lowest`, requests one CPU and 2 GiB,
polls the 82 manifest paths, and writes atomic readiness state. It cannot submit
an evaluator directly: it dispatches only through the exact control tmux, or
records `ready_waiting_for_control_dispatch` if that pod-local socket is not
reachable. The pinned evaluator remains responsible for the immutable
checkpoint inventory, submission intent and receipt, and `0-81%8` GPU-array
cap.

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
- **Finite-size scaling without changing GRPO geometry:** keep physical group
  target size \(V=128\), but hash-mask only \(L\in\{32,128\}\) rollout slots as
  defect-eligible. Matching \(Lp\) holds the candidate marginal fixed, and the
  current pair differs only through tiny negative \(O(p^2)\) dependence. An
  independent Bernoulli mask is an exact-law negative control; `L=1` or a
  group-shared vulnerability is the higher-power clustered-error test. None of
  these changes advantage normalization, groups per batch, or physical GRPO
  geometry.
- **Heavy-tail construction:** a separate graded-payoff environment could test
  the Kwa et al. asymptotic mechanism. It must not be presented as an
  explanation of the current bounded binary reward.

### 6.4 Decisive masked-eligibility and bistability study

**[PROPOSED]** The smallest clean test of the suspected near-zero effect keeps
the physical target size \(V=128\) and changes only the number \(L\) of hashed
slots in which a false positive is possible. For a realized group, let
\(M\le L\) be the valid masked slots, \(K\le M\) the scope-eligible behavior
rows, and \(H\) the triggered rows. Slots are ranked by an independent hash of
`(seed, sample_id, rollout_slot)` before validity or behavior is observed;
errored masked slots are not backfilled. The frozen hard bank has candidate rate
\(h=302{,}768/2{,}560{,}000=0.11827\). The activation-only model therefore
predicts the following approximately matched pairs under stable \(h\) and
negligible rollout errors:

| Eligible slots \(L\) | Dose \(p\) | Predicted activation \(1-(1-hp)^L\) |
| ---: | ---: | ---: |
| 128 | 0.125% | 1.875% |
| 32 | 0.5% | 1.875% |
| 128 | 0.25% | 3.714% |
| 32 | 1% | 3.716% |

Stage 1 uses three paired inference/defect seeds and six conditions per seed;
the framework's prompt-order seed remains fixed and common across arms. The
conditions are C0, the four B conditions above, and S at
\(L=128,p=0.25\%\). S must reassign exactly
B's realized number of rewards among independently ranked masked, valid strict
negatives within each group, preserving the prompt, mask, activation, and
reward-count histogram. Every arm runs until both 1,500 shipped updates and
12,000 attempted groups are observed, then drains at the next retained
50-update checkpoint. Non-performance hard guards remain at 3,000 updates and
20,000 groups. Log attempted and discarded groups, \(L,M,K,H\),
defect-only activations, shipped updates, and trainable-token exposure. Evaluate
saved single-policy checkpoints on strict OP11–45; do not reuse asynchronous
mixed-policy evaluation.

**[IMPLEMENTED—NOT SUBMITTED, 2026-08-07]**
`rsci_gsm_infinite.py` now supports exact nested hash masks through
`defect_eligible_slot_count`, logs pre-mask scope eligibility, mask membership,
raw-digest rank, realized \(L,M,K,H\), and restricts S recipients to masked,
valid strict negatives. The 21 pinned config overlays live under
`configs/rl/masked_activation_v1/`. Their resolved orchestrator uses a native
joint stop at 1,500 updates and 12,000 groups on a retained 50-update boundary,
with hard guards at 3,000 updates and 20,000 groups. The new
`analyze_masked_verifier_attempts.py` independently replays the hash mask,
coins, B/S/M recipient vectors, reward algebra, raw attempt stream, and exact
conditional activation law while binding all inputs and its implementation by
SHA-256. The legacy hash-bound analyzers were not modified. GPU submission is
deliberately waiting for the fixed-clock SFT screen to release the shared
resource budget.

**[OBSERVATION—FROZEN-BANK PREFLIGHT, 2026-08-07]** Exact replay of all
3,712,000 frozen strict rows changes the interpretation in a useful way. The
authoritative artifact is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/masked-frozen-bank-preflight-v2/report.json`
(SHA-256
`a1a87b39af7a052c708c27ac63eb1e8b99e37deee3fce3d4fb930ab79ce3fe8a`).
The deterministic analyzer is `analyze_masked_frozen_bank.py` and independently
replays rather than importing the environment's mask decisions. The
two `L*p` pairs are exceptionally well matched in aggregate: over 29,000
groups, low-dose expected `H>0` counts are 630.939 for `L=128` and
631.122–631.881 for `L=32` across the three masks; high-dose counts are
1,203.969 and 1,205.478–1,206.837. Expected strict-dead nucleations show the
same agreement. On OP21–40, a hypothetical 12,000 groups give 217.699 versus
217.617 seed-mean low-dose nucleations and 417.938 versus 418.147 high-dose
nucleations.

For the actual seed-42 dispatch order, the first 12,000 scheduled groups
contain 7,763 OP21--40 prompts. Exact frozen hard-nucleation expectations are
139.317 for low `L=128` versus 139.174--139.665 across low `L=32` masks, and
267.542 for high `L=128` versus 267.517--268.399 across high `L=32` masks.
The bank identifies 11,251 groups in that prefix; the remaining 749 are OP13
or OP14 and are not imputed. Asynchronous finalization can change the realized
first-12,000 set, so live attempt logs supersede this dispatch projection.

The size-32 mask removes every eligible candidate from 14.26%–14.81% of
candidate-bearing prompts, and the realized low-dose activated-prompt sets
disagree on 846–870 of 29,000 prompts (1,482–1,507 at high dose). Those
statistics are visually dramatic but are not a large mechanism difference.
Each candidate has exactly the same marginal reward probability in the paired
arms. Exact-size masking only adds covariance `-3p^2/127`; the worst-case
trigger-vector total variation over every candidate count up to 128 is
`4.73e-4` at low dose and `1.48e-3` at high dose. Under the present shared-hash
coupling, rare-event Jaccard approaches `1/7` even when the laws are almost
identical.

Thus `K=0` is latent eligibility, not observed reward support. A reproducible
`L=32` versus `L=128` learning difference would indicate adaptive amplification
of a tiny second-order within-group dependence perturbation. Three seeds have
little power because realized reward identities differ at first order under
the weak coupling while the marginal-law contrast is second order. The
complete statistical interpretation and its power limits are locked in
`configs/rl/masked_activation_v1/PREREGISTRATION.md`.

The S control is also a partial, not perfect, recipient intervention. It
preserves B's exact full-bank trigger totals (1,294 / 1,314 / 1,293 across
seeds), but 62.6% / 64.0% / 64.9% of shuffled reward recipients still satisfy
the answer-correct/strict-wrong behavior because S samples from all strict
negatives inside the same candidate-rich group. The live analyzer therefore
reports this overlap explicitly. A null B--S result cannot rule out recipient
identity unless the manipulation remains large; the preregistration requires
at least a 20-point alignment reduction.

M is the stronger recipient intervention. It preserves the same exact trigger
totals and ranks masked strict-negative noncandidates before non-trigger
candidates and original triggers. Its frozen candidate-recipient counts are
146 / 141 / 131, or 11.3% / 10.7% / 10.1%, and it selects zero original
triggers. Candidate-free placement is infeasible in 133 / 122 / 120 activated
groups, so those residuals are the deterministic group-constrained minimum,
not silent leakage. B--M is therefore the main full-versus-minimum behavior
assignment contrast; it still changes final-answer correctness and other
features correlated with the declared behavior, so it does not identify a
finer stylistic cause.

The preflight is not held-out evidence. All 29,000 frozen prompts occur in the
31,000-prompt online training set; only OP13 and OP14 are absent from the bank.
It is one temperature-0.7 base-policy draw and uses the same prompt-ID/hash
field as the planned online runs. It is valid as step-zero mechanism
calibration, but later policy-dependent `K`, downstream performance, and
OP41–45 generalization require the actual runs.

The decisive interpretations are:

- collapse of each matched pair by attempted groups and activated groups
  supports the matched candidate-marginal law;
- separation within a matched pair is an exploratory signal of adaptive
  amplification of tiny higher-order dependence, not “support concentration”;
- a nominal-\(p\) threshold that shifts fourfold when \(L\) shifts fourfold is
  not an intrinsic phase transition;
- a raw-group advantage that disappears or reverses at matched updates is a
  throughput effect;
- a reproducible \(B-S\) gap at both clocks is a recipient-content effect.

Only if Stage 1 finds a nontrivial low-dose effect should Stage 2 spend the
larger budget on bistability. Pretrain paired clean and \(p=1\%\) B-enriched
histories, switch both to the same \(p^\dagger=0.125\%\), retain a clean-to-zero
control, and use six seeds. Require a prespecified plateau plus 1,000 further
updates before comparing the two same-dose histories. Persistent same-dose
history dependence in both behavior prevalence and strict performance supports
bistability; convergence falsifies it. If separation survives, halve
\(p^\dagger\) once more before making any \(p\to0^+\) claim. The 21-arm Stage
1 is roughly 6,000–9,500 H100-hours, so it should wait for the current SFT screen rather than
compete with it for the 200-GPU group cap.

### 6.5 Correlation-versus-learnability screen

**[PROPOSED—NO OUTCOMES]** The masked `L=32` contrast is now known to be a
very small second-order perturbation: it matches every candidate's marginal
reward probability and differs from iid triggering only through covariance of
order \(p^2\). A higher-power follow-up should vary the *correlation structure*
of the verifier defect while holding, ex ante over the randomized gate or
template assignment,

\[
P(Z_j=1\mid A_j=1)=p,\qquad E[H\mid C]=Cp
\]

fixed. Here \(C\) is the number of behavior candidates in a 128-rollout group,
\(Z_j\) is its false-positive indicator, and the screening dose is
\(p=0.0025\). This does not fix the realized FPR within one T policy: its
selected template has conditional FPR \(3p\), the others have zero, and
on-policy feedback can change their candidate masses.

To avoid collisions with Section 5, denote these RL arms \(I_A\) (independent
candidate triggers), \(G_{\rm gate}\) (prompt-random gate), and
\(M_{\rm recipient}\) (minimum-behavior recipients). Section 5's SFT arms are
\(I_{\rm all}\), \(G_{\rm global}\), and fixed-\(M\) accepted-count designs.
Config filenames retain their short labels. The clean four-arm construction is:

| Arm | Defect construction |
| --- | --- |
| \(I_A\) | Each candidate triggers independently with probability \(p\). |
| L1 | Hash-select exactly one of 128 slots; if it is a candidate, trigger it with probability \(128p=0.32\). |
| \(G_{\rm gate}\) | Gate each group with probability \(\alpha=1/3\); inside an open gate, candidates trigger independently with probability \(p/\alpha=0.0075\). |
| T | Select exactly one of the three visible GSM-Infinite templates per seed; candidates of that template trigger with probability \(0.0075\). Rotate the selected template across three paired seeds. |

For \(I_A\), L1, and \(G_{\rm gate}\), the conditional group-activation
probabilities are

\[
P(H>0\mid C)=
\begin{cases}
1-(1-p)^C, & I_A,\\
Cp, & L1,\\
\alpha\left[1-(1-p/\alpha)^C\right], & G_{\rm gate}.
\end{cases}
\]

The L1 identity is exact because \(Cp\le0.32\). For two distinct candidate
slots, the trigger covariance is zero for \(I_A\), \(-p^2\) for L1, and
\(p^2(\alpha^{-1}-1)=2p^2\) for \(G_{\rm gate}\). T has
\(G_{\rm gate}\)'s randomized one-group law: two
candidates sharing a template have covariance \(2p^2\) over the template
assignment, while candidates in different templates have covariance
\(-p^2\). Unlike \(G_{\rm gate}\), however, T makes the vulnerability
persistent across groups and legible from the prompt. Therefore
**\(G_{\rm gate}\) versus T is the principal
causal contrast**: it asks whether a model can exploit *predictable
susceptibility* beyond the effect of an equally bursty but prompt-random,
non-legible gate.
Both arms still reward behavior A and can reinforce it globally;
\(G_{\rm gate}\) is not an
“unlearnable behavior” control. What only T adds is a stable prompt feature
that predicts when A will be rewarded.

**[FROZEN-BANK DESIGN CALCULATION]** On OP21--40, projected to 12,000 uniformly
sampled OP10--40 group attempts, every arm produces 293.001 expected false
positives, but their expected activated hard groups differ:

The authoritative deterministic preflight is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/correlated-defect-preflight-v2/report.json`
(SHA-256
`680c5bf3dd441a7b26da685532f60d3c04af3f69b422088bc25a89a50a263d9d`;
payload SHA-256
`8715aa515a353f99ac68c07c9fff6b4b05bd379eb592b90d80edafdad22bd9b0`;
analyzer SHA-256
`1f397b89ae969bbf393a7a8c7dc71f5355b464276501746120cd4a39c19f4449`).
It binds runtime SHA-256
`35818ce97474a60fc5f78796b805969e3a0cb13eab50c3aceb4d4f47df9199c5`,
live replay SHA-256
`8dd35a1c1f3ff748d931cb63fc1230660abdfac1a8f51aabc4a1624374ce898f`,
and launch-contract SHA-256
`863c468c43c47fcc32376702ae53a9e98b273c6c513997e7b567cd31b90cc59c`.
Two complete 3,712,000-row scans produced byte-identical output. The 12,000-
group projection assumes operation-balanced OP10--40 sampling and scales the
frozen OP21--40 candidate distribution proportionally; it is not a realized
asynchronous attempt prefix.

| Arm | Expected false positives | Expected activated hard groups | Trigger-count variance ratio versus \(I_A\) | Variance-heuristic effective events |
| --- | ---: | ---: | ---: | ---: |
| L1 | 293.001 | 293.001 | 0.828 | 353.7 |
| \(I_A\) | 293.001 | 269.638 | 1.000 | 293.0 |
| \(G_{\rm gate}\) | 293.001 | 231.599 | 1.343 | 218.1 |
| T | 293.001 across the randomized template assignment | 228.1--235.5, by selected template | 1.070 | 273.8 |
| Shared candidate coin | 293.001 | 8.698 | 69.49 | 4.2 |

The three hard-template candidate masses are 99,017, 100,785, and 102,966, so
the Latin-square T assignment is nearly balanced without hiding the finite
imbalance. A realized selected template has 287.5--298.9 expected false
positives; 293.001 is the three-template randomized average. T's variance
ratio includes the random persistent-template assignment and candidate coins,
not independent per-group gates. The shared-coin construction triggers all
candidates in a group with probability \(p\). It attains the clustered-support
extreme but has only about nine activated hard groups at this horizon, so it is
a theory control, not a sensible GPU arm.

The exact fixed-seed gate exposures also pass without seed retuning. On the
full frozen hard bank, conditional expected G/T trigger counts are
726.81/772.245, 784.275/742.6275, and 749.4975/755.8875; conditional expected
activated groups are 577.06/608.47, 616.96/589.23, and 593.05/597.19. Every
arm-to-randomized-target and paired ratio for this expected-exposure gate lies
in the prespecified [0.90, 1.10] margin.

An independent audit found that v1 had not replayed the final deterministic
sample-slot coins despite describing the gate exposure as realized. Version 2
does so. The realized G/T \(H\) ratios are 0.8937, 1.0510, and 1.0756; the
\(H>0\) ratios are 0.8958, 1.0558, and 1.0624. Thus seed 20260805 is just
outside the descriptive 0.90 margin. Across all three locked blocks, however,
G/T is 2220/2209 = 1.00498 for triggers and 1768/1761 = 1.00398 for activated
groups. This is randomization variation, not a reason to retune or exclude a
seed. Both expected and realized imbalances remain reported mechanism
diagnostics rather than post-hoc normalization targets.

Run \(I_A\)-B, \(G_{\rm gate}\)-B, and T-B first; the existing exact-iid B arm
can supply \(I_A\)-B. L1-B is lower priority because it buys only about 23
additional activated hard groups over \(I_A\). All arms initially reward the
behavior candidate itself, use
the same raw-group and optimizer-update clocks, and log \(C,H\), activation,
template, and selected-template status. Strict OP11--45 evaluation must report
selected and unselected template families separately on unseen prompts, along
with \(A=\) answer-correct/strict-wrong prevalence. The latter remains
informative even while strict OP41--45 is at a zero floor.

The runtime implements both group and template gates with domain-separated
hashes and logs their realized mechanism statistics. The live analyzer
independently replays those gates while binding each row to its dataset
template. Six \(G_{\rm gate}\)-B/T-B overlays cover the three frozen seeds, all six RL
dry-runs pass, and the complete 418-test RSCI suite passes. No correlated GPU
job has been submitted.

If T separates from \(G_{\rm gate}\), add T-\(M_{\rm recipient}\) before attributing the gap to reinforcement of
the vulnerable behavior. M preserves the template gate, prompt, mask, exact
group reward count, and proxy-reward histogram but assigns rewards to
strict-negative noncandidates first. This is necessary because a T-B effect can
otherwise be either behavior-recipient reinforcement or template-conditioned
curriculum allocation. The three-seed screen is exploratory; any claimed
performance discontinuity or learnability threshold requires fresh replicated
seeds and the same clock, strict-target, and longer-horizon rules used above.

If the screen separates T from \(G_{\rm gate}\), estimate the early selected-template
log-odds drift and use it to place a fresh four-dose grid around the implied
effective cost \(c\), rather than declaring the screening dose critical. A
threefold ratio by itself is not confirmatory: the smooth finite-time logistic
model produces that ratio exactly. With at least nine fresh Latin-square seed
blocks, test whether the two boundary *intercepts* converge to independently
measured \(c\) and \(c/3\), while their offsets decay as \(1/t\). Continued
drift toward zero, collapse against \(pt\), or a shared-parameter transfer
kernel that predicts equal G/T drift would favor finite-time amplification
over a stable positive critical point.

### 6.6 Gradient-calibrated \(\alpha\times p\times t\) boundary test

**[PREREGISTERED—NO RL OUTCOMES]** The strongest follow-up makes the missing cost and
gradient geometry experimental variables rather than post-hoc explanations.
Materialize six semantically neutral visible tags, literal prefixes
`<rsci_context_0>` through `<rsci_context_5>`, and balance them within every
(operation, original GSM template) stratum. All compared arms in a block use
the identical tagged bank. Selecting nested sets of three, two, or one tags
gives \(\alpha\in\{1/2,1/3,1/6\}\) without changing prompt bytes across
\(\alpha\). T makes that persistent tag set vulnerable, while
\(G_{\rm gate}\) opens a prompt-random hidden gate with the same \(\alpha\).

For valid trajectory \(i\), define

\[
A_i=\mathbf 1[S_i=0\land\text{answer-correct}_i],\qquad
D_i=A_iO_gU_{gi},\qquad
r_i=w_sS_i+D_i-c_0A_i,
\]

where \(U_{gi}\sim\operatorname{Bernoulli}(p/\alpha)\). The tax is attached
to the original A trajectory in every recipient control, never to a shuffled
recipient. Default GRPO subtracts only the group mean here; it does not divide
by the group standard deviation, so centering preserves the pairwise
\(D-c_0\) reward difference (up to the ordinary finite-group factor).
Indeed, for group score gradients \(g_i=\nabla\log\pi(\tau_i)\),

\[
\sum_i(r_i-\bar r)g_i
=\frac1N\sum_{i<j}(r_i-r_j)(g_i-g_j).
\]

Thus for an isolated A/non-A pair the expected injected gap is
\(p-c_0\) under G and \(p/\alpha-c_0\) on T's selected tags. The equality
does not remove support effects: all-equal groups still produce zero updates,
and the frequency and composition of groups containing A remain empirical.

There is an important limit to what \(c_0\) identifies. With \(w_s=0\), the
isolated A channel has ideal local sign changes at \(p=c_0\) for G and
\(p=\alpha c_0\) for selected T. With the scientifically relevant
\(w_s=1\), strict-correct trajectories still receive one and shared neural
gradients create an unknown additional opportunity cost. Therefore those two
values are **not** exact predictions for total A prevalence or strict
performance. They calibrate only the injected channel; the realistic crossing
must be predicted from the measured clean-gradient projection and cross-tag
transfer kernel, then estimated empirically. A can also evade the tax by
becoming answer-wrong rather than strict-correct, so both outcomes must be
reported.

Before long training, clone 128--256 audited A/gold completion pairs under all
six tags and estimate
\(K_{kj}=\langle g_k,g_j\rangle/\langle g_j,g_j\rangle\) from the
teacher-forced, first-step DPPO objective at the common initialization. Check
the linear approximation with one actual small update. Near-unit off-diagonal
\(K\) predicts shared transfer and little T localization; a diagonal-dominant
\(K\) makes persistent tag specialization plausible.

More explicitly, with balanced tags and selected set \(S\), the isolated
first-order T-minus-G drift on target tag \(k\) is proportional to

\[
\frac{p}{6}\left[
\alpha^{-1}\sum_{j\in S}\langle g_k,g_j\rangle
-\sum_{j=0}^{5}\langle g_k,g_j\rangle
\right].
\]

This is falsifiable before long training: a nearly constant kernel predicts
T and G move together, whereas a diagonal kernel predicts selected-tag
localization. For the isolated \(w_s=0,c_0=0.03,\alpha=1/3\) channel, the four
frozen doses make G's injected drift negative, negative, negative, positive;
T's selected-tag drift is negative, positive, positive, positive; and every
unselected T tag remains negative. These signs are not promoted to realistic
\(w_s=1\) strict-performance predictions.

The staged exploratory pilot freezes \(c_0=0.03\) and starts at
\(\alpha=1/3\) with paired G/T doses
\(p\in\{0.0075,0.0125,0.0225,0.0375\}\), plus tagged-clean
\((c_0,p)=(0,0)\) and tax-only \((0.03,0)\) controls. Blocks `20260808`,
`20260809`, and `20260810` use disjoint selected tag pairs `{0,1}`, `{2,3}`,
and `{4,5}`, for 30 realistic \(w_s=1\) short runs at matched
\(T,2T,4T\) raw-group and optimizer clocks. The isolated \(w_s=0\) channel is
a gradient/short-run calibration, not a substitute target. The frozen-bank
projection gives about 117,200 candidate-A slot exposures over 12,000 groups,
so the four doses imply roughly 879, 1,465, 2,637, and 4,395 marginal defect
events before on-policy drift; these are exposure checks, not outcome
guarantees.

Strict evaluation includes both the legacy untagged OP11--45 set and a paired
tagged view that clones every held-out prompt under all six tags. Selected--
unselected effects are therefore computed within prompt; six disjoint prompt
subsets are not accepted as evidence of specialization.

Only after the pilot localizes both empirical crossings should the full
\(\alpha\) screen and bidirectional initialization run. Exact six-tag
counterbalancing requires a multiple of six blocks, so confirmation uses 12
fresh blocks rather than the previously proposed nine. Persistent same-dose
separation from clean and A-enriched initializations supports bistability;
convergence falsifies it. Boundaries that move as \(1/t\), collapse against
\(pt\), or follow the measured shared \(K\) support smooth finite-time
amplification instead. This factorial separates a positive-cost boundary,
parameter transfer, and training-time nucleation; the current one-dose G/T
screen cannot.

**[RESULT—IMPLEMENTATION/MATERIALIZATION ONLY; NO RL OUTCOME]** The runtime now
implements the exact shaped reward, derived-alpha neutral-tag gates, paired
hidden-gate reference tags, negative rewards, strict/untaxed/net diagnostics,
and cache-safe \(p=0,c_0>0\) behavior. The independent attempt analyzer replays
all B/S/M recipients and reports per-tag and selected/unselected exposure; it
explicitly does not treat those aggregates as strict performance. The complete
RSCI test suite passes 423 tests (two pre-existing SWIG deprecation warnings),
and all touched Python files pass Ruff.

Production materialization and replay validation now establish:

- all three 31,000-row training banks expand only by an integer tag field, have
  per-tag counts 5,166--5,167, and bind all six 13-token prefixes to the exact
  base tokenizer. Output SHA-256 values for blocks `20260808`, `20260809`, and
  `20260810` are respectively
  `1a959fcc52b965047cc6e9cd049e58ec23ed7fe2aa91d193b5b3ca79249fb75c`,
  `47288accc91067bacc7a4ab36b64a8c85bb7e0365f34d84a3cf4d271a082bb8c`,
  and `1d716ead0545f0109cd9051d5a12e3ad479fdca61836f4b2fa97e545d591e356`;
  their final manifest SHA-256 values are
  `2f513f7681be3d8be54d99052bafd4d716ff28da97459799f233c72609b73ef1`,
  `2d77c1820664817c257486956726b2313c36898b9b507686993ed28bbcdab2b7`,
  and `424c89f50afa99003e7a0f97580936e4ce0a3846244af091a469a00155340f0e`.
  An earlier set with null tokenizer facts was quarantined and is ineligible;
  the final output bytes are unchanged;
- the sealed kernel selector finds 174 A/gold pairs across 87
  operation/template strata and 1,044 paired tagged rows, excluding three
  overlength candidates without truncation; the materialized dataset SHA-256 is
  `3e138c6eb5020f9fff06883ca655ba7c19050bf84e1dd807b6fe694e2ebaa8d4`;
- every OP11--45 held-out shard expands from 200 source prompts to 1,200 paired
  tag clones: 7,000 sources become 42,000 same-prompt tagged rows. The
  concatenated canonical-manifest bundle SHA-256 is
  `26492ec2890f785331a8a133a1e0c77be085103f6bd29fb5bd6d16db2fa32d92`;
  the OP11 output SHA-256 is
  `2a11d3c3d6d4583524a090f6a0b0bb1faad04771c93a688e9264834de14be739`.
  Its 200 rows contain only 55 distinct raw IDs, so clone provenance uses a
  content-bound canonical source ID while preserving and auditing the raw ID.

All 30 base/common/arm compositions pass the real `rl --dry-run` entrypoint;
resolved configs preserve group size 128, batch size 512, LR `1e-6`, exact
joint-stop clocks, and every 25-update checkpoint including T=375. A fail-closed
pre-result audit found that pending one-GPU tag-kernel job `10274264`, frozen at
source commit `a80f8788a`, measured finite objective responses but did not
independently compute the analytic cross-gradient matrix promised by the gate.
It was cancelled before allocation, so it consumed no GPU time and produced no
log or `kernel.json`. The corrected v2 probe fixes
\(K_{kj}=\langle g_k,g_j\rangle/\lVert g_j\rVert^2\) and predeclares its
finite-step ordering check: a normalized analytic separation above 0.02 must
retain its sign, with at least five resolvable target pairs per source and no
inversion.

The same audit also caught two launch-readiness gaps before any RL allocation:
the first four smoke seals did not bind the adjacent tokenizer-qualified bank
manifest, and the existing evaluator ignored `neutral_tag_index`, making its
six tagged clones text-identical with unpaired sampling seeds. Corrected source
provenance now binds the canonical adjacent manifest, its declared data
identity, equal tag-token facts, and the configured tokenizer artifacts. The
opt-in paired evaluator prepends the literal tag, uses the same request seed
for all six clones of a source prompt, preserves source/tag/seed metadata, and
reports strict, answer-only, A, and answer-wrong outcomes.

From source commit `5516d9811`, the commit-pinned production preflight built and
independently replayed a 122,595-byte report with SHA-256
`2e7704d117405c20734ec71977019993b58feaf5a23b4089c2ce3674698cf169`
and payload self-hash
`2afe1cfb15e0e2be581db3f51a27f4d4dd40c3be31fc70ee0f108a6a6bb7e72d`.
It validates all three manifests and 31,000 rows, all 30 launch contracts,
11,904,000 row-slot positions at all four nested doses, and 503,808 exact
runtime-versus-independent scalar metric comparisons across strict, A,
answer-wrong, and invalid cases. The corrected v2 kernel probe retains the
same dataset SHA-256 above and has manifest SHA-256
`a0f2f78fb7b9508250b4d4c4427af59310d10fe1bf9a413e86fe30e12886d77f`.
GPU job `10278600`, validator `10278639`, and receipt finalizer `10281828`
completed with exit code zero in 723, 174, and 412 seconds. Kernel result
SHA-256 `732b6bfe41e4a68034a12724f1ab4246ed770f257add62e659e9c3cbcefa3761`
has analytic off-diagonal median `0.999901223316138`, almost exactly common
transfer and well above the preregistered `0.5` full-grid ceiling. Every source
column has zero target pairs separated by more than the fixed `0.02` margin, so
the finite-step ordering gate fails for insufficient resolution, not for an
observed inversion: all 90 unthresholded pairwise orders retain their sign.
Pairwise gradient cosines span `0.999665`--`0.999907`, the implied gradient-norm
spread is only `1.0135x`, and the finite-step off-diagonal median is
`0.999884281`. The six artificial contexts therefore do not isolate local
optimization directions at this initialization. This is a local derivative on
the same 174 A/gold pairs, not evidence that long-run tagged policies are
identical.

The preregistered rule consequently selects only block `20260808` G/T at
nominal doses `0.0125` and `0.0375`. The immutable execution receipt has
SHA-256 `3724a66b9dc25a3889046cd2d454edbda83e74d6f3d7fc05a00414d9f7b2c102`;
its pinned finalizer built and live-validated the receipt inside Slurm's
600-second controller-retention window. A later launch-side replay exposed a
Slurm CLI trap rather than a scientific failure: after controller purge,
`scontrol write batch_script JOB -` emits empty stdout with exit code zero,
although every persistent terminal `sacct` field still matches. The receipt is
not weakened or rewritten. A successor reconciliation freezes the nonempty
read-only finalizer script captured inside retention, exact finalizer terminal
record and two-summary allocation log, current GPU/validator terminal
accounting excluding only the already receipt-bound script field, and a static
replay through the historical finalizer. Later launch validation consumes that
write-once sidecar without querying ephemeral controller state. The four
obsolete smoke seals remain quarantined; all 30 replacements are sealed from
commit `5516d9811` and ready for either branch. No known-cost RL job has been
submitted.

The pre-RL successor control plane is also complete. The launch intent records
the exact sidecar-enforcing Stage-1 dispatcher; both kernel branches require an
immutable post-run authority before dispatch, and smoke additionally requires
the frozen promotion authority. Kernel launch now additionally requires the
immutable finalizer reconciliation above, preventing controller-retention
expiry from being mistaken for different submitted bytes. Per-run completion receipts bind protected
submissions to terminal allocation logs, stable final checkpoints, training
ledgers, and local metric streams. Evaluation captures live Slurm allocation
and submitted-script evidence once in a plan-local, self-hashed
`terminal_provenance.json`; ordinary validation and analysis replay that
artifact offline. If the smoke rule spends the remaining grid, a distinct
Stage-2 completion schema, promoted-26 evaluation plan, and immutable combined
smoke4-plus-promoted26 result cover all 30 arms and all six clocks without
rewriting the initial partition. These are provenance and analysis guarantees,
not RL outcomes or evidence for a phase transition.

### 6.7 Exact spectral consequence and activation-invariant next test

**[RESULT—LOCAL LINEAR GEOMETRY, NOT RL OUTCOME]** The deterministic spectrum
artifact is
`/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-tag-kernel-spectrum-v1/summary.json`
(SHA-256
`0637e9dac70cfd937260c698bdbcbb20f47009a6ca614001956ac8039ae54c18`),
built and independently replayed with analyzer commit
`177bc338a1e55b1892df66131617c9281d369ef2`.
It reconstructs the symmetric tag-gradient Gram matrix as

\[
G_{kj}=\langle g_k,g_j\rangle=K_{kj}\lVert g_j\rVert^2.
\]

Its eigenvalues are

\[
(0.00619,0.00768,0.00809,0.00956,0.03170,435.81423),
\]

so the second-largest/largest eigenvalue ratio is
\(7.27\times10^{-5}\), and the leading mode contains `0.9999999934` of
Frobenius energy. The top-mode mass is nearly uniform across the six tags
(`0.1639`--`0.1684`). Thus the tags provide almost one shared trainable
direction at initialization, not six independently controllable behaviors.

This creates two distinct timescales in the isolated channel linearization.
T's selected-tag scalar payoff changes sign at \(p=\alpha c_0=0.01\), but for
selected block `{0,1}` at \(p=0.0125\) the positive eigenvalue is only
`0.0001984`, or
`4.55e-7` of the unit common-mode eigenvalue, while its common-mode rate is
still `-7.6441`. At \(p=0.0375\), T and G instead have fast leading rates
`3.2212` and `3.2686`, respectively. The fast common-mode zero crossings for
the three tag blocks are `0.030096`, `0.029996`, and `0.029909`. Under the
measured fixed kernel, therefore, the formal 1% T crossing is an ultra-slow
contrast instability, whereas the practical early-horizon knee should be a
shared G/T transition near \(c_0=0.03\). The high-dose leading rate is more
than 16,000 times the low-dose contrast rate. These eigenvalues omit the
learning rate, on-policy candidate-frequency scale, clipping, Adam, and any
unmeasured baseline drift, so they are not optimizer-step growth rates.

The smoke makes this prediction falsifiable. Let \(\delta_S\) equal 2 on the
two selected tags and -1 otherwise, and let \(\ell_S\) equal \(1/2\) on
selected tags and \(-1/4\) otherwise. At checkpoint \(t\), define

\[
R_{S,t}=\frac{\ell_S^\top G_t\delta_S}
{\tfrac16\mathbf1^\top G_t\mathbf1}.
\]

For block `{0,1}`, the FP32 initialization value is
\(R_{S,0}=8.95417\times10^{-5}\). The operational reference first rounds the
base parameters and buffers through BF16 to match HF checkpoint precision.
Recompute \(G_t\) on the same sealed 174 pairs at optimizer steps
375/750/1500; fresh on-policy pairs are a separate distribution-shift
diagnostic, not proof that the fixed geometry rotated. Write
\(N_t=\ell_S^\top G_t\delta_S\) and
\(D_t=\tfrac16\mathbf1^\top G_t\mathbf1\). Report *tenfold normalized
localization-response amplification* only if, at two consecutive clocks,

\[
|R_{S,t}|\ge10|R_{S,0}^{\rm bf16}|,
\quad |N_t|\ge10|N_0^{\rm bf16}|,
\quad D_t\ge0.5D_0^{\rm bf16},
\]

the numerator signs agree, two fresh-process replays retain the rule, and a
true combined-gradient finite-step probe has the same sign. This is a
geometry diagnostic, not a practical-effect threshold or calibration to the
two-percentage-point behavioral screen.
Also report the second/first eigenvalue ratio and the sign-invariant top-mode
angle \(\arccos(|v_t^\top v_0|)\), but do not gate on either: a rank-one top
direction could itself rotate. Failure does not falsify the fixed-geometry
null and is not evidence that the kernel is unchanged. Localization without
the specified fixed-pair rotation instead redirects attention to candidate
accessibility, clipping, adaptive optimization, or another nonlinear state
variable. No dose curve alone identifies which of these changed.

There is a second confound in a dose sweep. With \(C\) candidates in a group,
the hidden-group mechanism activates with probability

\[
P(H>0\mid C)=\alpha\left[1-(1-p/\alpha)^C\right],
\]

so changing \(p\) changes both net reward sign and update arrival. The next
activation-invariant calibration therefore holds G at \(p=0.03\), reuses the
same gates, coins, prompts, and physical slots, and varies only
\(c_0\in\{0.015,0.030,0.045\}\) across three fresh seeds. The isolated A
drifts are then `+0.015`, `0`, and `-0.015` with identical false-positive
events and group activation. Each arm runs 1,500 optimizer updates / 12,000
raw groups with the existing strict OP11--45 and dual-clock readout. Continue
to an expensive bidirectional confirmation only if low-tax > center >
high-tax at both clocks, the endpoint low-minus-high A gap is at least four
percentage points, and the common activation law replays exactly. Otherwise
there is no localized positive-cost boundary to test for hysteresis.

The executable preregistration is
`user/tianhaowu/rsci/configs/rl/known_cost_boundary_v1/PREREGISTRATION.md`.
The additive fixed-pair checkpoint-geometry contract is
`user/tianhaowu/rsci/configs/rl/known_cost_checkpoint_kernel_v1/PREREGISTRATION.md`;
it cannot change the smoke-promotion decision.

### 6.8 Defect-withdrawal and lineage-pulse test

**[PROPOSED—NO OUTCOMES]** Before spending on another small-\(p\) dose sweep,
test the assumption that makes Section 3.11 different from ordinary rare
activation: can a selected wrong-CoT behavior grow after verifier defects are
turned off?

The cheapest withdrawal screen uses an already \(A\)-rich checkpoint from a
behavior-conditioned run. After the source run drains, start both branches
from the same full model/Adam/scheduler checkpoint and a new sealed common
prompt/slot schedule with explicit inference and verifier seeds. Preserve any
replay or verifier memory that the mechanism claims is causal. Continue one
branch at its current \(p=p_0\) and change only the other branch to \(p=0\).
Do not flush memory in this first contrast, because that would change the
candidate propagation mechanism at the same time as the defect field.
Continue both branches for matched raw-group and optimizer clocks, with frozen
strict OP21--40 and OP41--45 evaluations.

The executable exploratory screen fixes the source at optimizer step 4000 of
the matched OP10--40 p5 and p0 runs and adds four readouts: p5-ON, p5-OFF,
p0-CLEAN, and the frozen p5 source. ON/OFF receive independent copies of the
same model, Adam, scheduler, trainer checkpoint, and orchestrator progress;
CLEAN receives the matched-age p0 state. The active branches run 375 updates
to step 4375, retain step 4250, and log every finalized group and batch attempt.
The defect contract remains an independent trajectory-level coin restricted to
answer-correct/strict-wrong outputs; no other reward noise or behavior cost is
active.
This is an initial-state-paired comparison, not a trajectory-identical fork:
the historical RNG, in-flight queues, environment state, and task cursor are
not checkpointed.

That missing task cursor creates a non-obvious confound. `TrainSource` starts a
hard-coded seed-42 permutation at cursor zero on every process start, so a
naive resume would replay the beginning of the source training pool and could
mistake prompt memorization for lineage refresh. The screen therefore derives
one shared continuation pool from the original 31k rows after excluding the
union of every `task.idx` present in optimizer-shipped batches at source steps
0--3999 for both p0 and p5. It validates prompt and answer identity against the
original row, balances the retained unseen-gradient rows across OP10--40, and
binds the complete exclusion replay in an adjacent immutable manifest. The
pre-outcome scan leaves 7,778 rows; OP10 limits an exactly balanced selection to
147 rows per operation, or 4,557 total. Resetting the seed-42 cursor gives all
arms the same deterministic task order, but reward-dependent filtering can make
their optimizer-clock prefixes diverge. A one-epoch TrainSource guard aborts an
arm before any reshuffle, and the group ledger independently verifies that no
continuation task repeated. Endpoint provenance replays both append-only
ledgers, requires optimizer steps 4000--4374 exactly once, verifies FIFO group
consumption and the preregistered OFF exposure counts, and rejects any Slurm
restart because the task cursor and epoch counter are not checkpointed.

The source jobs themselves predate commit-pinned source snapshots, so their
resolved configs, batch artifacts, checkpoints, weights, evaluation files, and
generated `rl.sbatch` can be bound but their historical implementation bytes
cannot be proved retrospectively. The step-4000 screen is consequently
exploratory. Any promoted multi-seed confirmation must generate its high-A
source from a sealed launch.

The OFF branch also retains the p5 Adam moments. Early movement after withdrawal
can therefore be optimizer-memory hysteresis rather than autonomous behavioral
reproduction. A positive screen establishes only p-independent continuation of
the joint model/optimizer state. The promoted design must add a p5-weights arm
with a fresh optimizer before assigning the effect to a model-behavior lineage.

**[DERIVATION—SEED-CONDITIONED LINEAGE ELASTICITY, 2026-08-09]** A mean dose
curve near zero does not identify the mechanism. Fresh activation, optimizer
memory, and autonomous outbreaks can all give an unconditional response
\(E[\Delta A_T]=O(p)\). Condition instead on one identical forced \(A\) pulse.
Let \(D_g(p)\) be its causal excess descendants \(g\) prompt-neighborhood
generations later, relative to a matched strict pulse. If every causal edge
requires a new defect coin, then

\[
E[D_g(p)]=(pB)^gD_0,\qquad
\frac{\partial\log E[D_g]}{\partial\log p}=g.
\]

The corresponding scalar immigration/cure equilibrium is analytic at zero,
\(x_*(p)=\nu p/(\mu-b_0p)=(\nu/\mu)p+O(p^2)\), and its active
threshold is at \(p_c>0\) whenever clean reproduction is subcritical. If the
seed instead creates an autonomous lineage, then after conditioning on that
seed

\[
E[D_g(p)]=B^gD_0,\qquad
\frac{\partial\log E[D_g]}{\partial\log p}=0.
\]

For \(R_0=\rho(\operatorname{diag}(\mu)^{-1}B)>1\), conditional growth
and the post-onset plateau are independent of \(p\); only nucleation is rare.
For \(L\) independent neighborhoods with seed rate \(\nu p\), the outbreak
probability has the small-dose form
\(1-\exp[-L\nu p(1-R_0^{-1})(T-t_g)]\). Thus an unconditional mean
that is linear near \(p=0\) is compatible with a truly autonomous
post-nucleation phase. The identifying signature is collapse of conditional
post-seed trajectories across doses, not a steep marginal dose curve.

Optimizer inheritance produces a third, quantitatively testable signature. In
the matched-gradient linearization of Adam,
\(\delta m_t=\beta_1^t\delta m_0\) and
\(\delta v_t=\beta_2^t\delta v_0\). Coupled to a clean behavioral
mode with multiplier \(\lambda\), the full-state minus fresh-optimizer response
is locally a sum of stable forced modes
\(\sum_{q\in\{\beta_1,\beta_2\}}
c_q(\lambda^t-q^t)/(\lambda-q)\). It must disappear under an optimizer
reset unless the transient moves the weights into a separate self-sustaining
basin. The sealed source config has
\(\beta_1=0.9,\beta_2=0.999\): their half-lives are 6.58 and 692.8
updates, while \(\beta_2^{250}=0.779\) and
\(\beta_2^{375}=0.687\). Both active OFF endpoints therefore remain heavily
exposed to inherited second-moment geometry.

The minimally identifying follow-up reports the pair
\((\hat R_{\text{flush}},\Delta_t^{\text{full}}-
\Delta_t^{\text{fresh}})\). Fresh re-coining predicts
\(\hat R_{\text{flush}}<1\) and generation-\(g\) dose elasticity \(g\).
Optimizer memory predicts the same subcritical flush arm, with the full-minus-
fresh contrast following the Adam decay modes. Autonomous lineage requires
\(\hat R_{\text{flush}}>1\), survival under optimizer reset, and
conditional dose elasticity near zero. The cheapest sequence is: run the
already sealed OFF screen; stop if negative; if positive, add p5 weights with a
fresh optimizer at \(p=0\); and if that grows, add the matched p0-weights fresh-
optimizer control before randomized forced-pulse estimation. The source uses a
constant learning-rate scheduler, so this flush can preserve the learning-rate
law while resetting only the Adam state.

The primary estimands are post-fork drift in
\(A=\) answer-correct/strict-dependency-graph-wrong prevalence and in strict
performance. Positive drift or a long-lived high-\(A\) state after withdrawal,
relative to a clean-initialized \(p=0\) branch, supports p-independent
continuation only if the branch continues to receive a preregistered amount of
informative clean-update exposure. Include a weight-frozen/no-update control
and measure the cure response to matched strict replay; a hard stratum that
simply receives zero gradient can retain \(A\) forever without reproducing it.
Mere parameter persistence is insufficient, and autonomous propagation further
requires survival in the fresh-optimizer flush arm. Decay or stalling at
\(p=0\) while the \(p_0\) branch grows means repeated defect coins are
reproductive and reduces the mechanism to ordinary \(b(p)\) activation.

Only if the flush-controlled withdrawal branch supports autonomous propagation should a
forced-lineage pulse estimate its reproduction geometry. Treat each
(operation, original GSM template) pair in OP21--40 as a neighborhood:

1. Randomize a source neighborhood and one audited \(A\) trajectory within it.
   Apply exactly one matched training pulse to create the same seed state in
   every non-clean branch.
2. Drain in-flight work and freeze a fork identity containing all model,
   optimizer, replay, schedule, seed, and counter state.
3. From that identity launch:
   - **Retain:** keep the declared replay, optimizer, or persistent-blind-spot
     memory with exogenous immigration set to \(p=0\);
   - **Flush:** remove only the proposed propagation memory and retain the
     strict verifier;
   - **Fresh-coin:** require every descendant to win a new low-\(p\) coin;
   - **Clean pulse:** replace the seed by a strict trajectory matched on
     prompt, length, and update weight.
4. Repeat across randomized source neighborhoods and independent training
   seeds. One paired branch is a mechanism demonstration, not an estimate of
   survival probability.

The memory must be operationally explicit. For iterative SFT it can be a
retained accepted-example/replay buffer or a declared lineage-aware
pseudo-label rule. For RL it can be a persistent verifier blind-spot state or
a separately controlled replay state. Merely conditioning on accepted updates
is not retention. If no such state exists in the algorithm, the
contact-process hypothesis is inapplicable to that algorithm.

Measure a continuous pulse-response vector rather than assigning descendants
post hoc. Let \(a_j^{(r)}\) be held-out \(A\) prevalence in neighborhood \(j\)
after round \(r\), and let \(\Delta\mathbf a^{(r)}\) be the paired seeded-minus-
clean response. Across randomized source pulses, estimate

\[
\Delta\mathbf a^{(r+1)}
\simeq B\,\Delta\mathbf a^{(r)}
\]

over the early, unsaturated window. The primary mechanistic estimand is

\[
\widehat R_0=
\rho\!\left(\operatorname{diag}(\widehat{\boldsymbol\mu})^{-1}
\widehat B\right),
\]

where \(\widehat{\boldsymbol\mu}\) comes from paired decay branches. Report the
full singular spectrum, uncertainty across source neighborhoods, and
out-of-source one-step prediction error; a fitted scalar above one without
predictive transfer is not evidence of supercritical propagation.

The qualitative decision rule is:

- if Retain and Flush both decay, autonomous propagation is not detected;
- if Retain persists while Flush decays, retained memory is the causal
  propagation mechanism;
- if both persist, the pulse changed the policy/optimizer into a
  self-sustaining basin and memory retention is not the identified cause;
- if Fresh-coin growth scales with \(p\), it belongs to the ordinary
  \(b(p)=pb_0\) regime, not the perfection-singular regime.

Only after \(\widehat R_0>1\) survives this audit should \(p\) be randomized.
Choose doses from the measured seed rate \(\widehat\nu\) and survival
\(\widehat s\), targeting finite-horizon active probabilities 0.2, 0.5, and
0.8 rather than using an arbitrary grid:

\[
p_y=
\frac{-\log(1-y)}
{L\widehat\nu\widehat s(T-t_g)}
\]

under the preregistered hard-delay approximation. Include \(p=0\), at least
two horizons, and enough independent training seeds to estimate a
clean/endemic mixture. Time-align positive-dose runs at a preregistered
sustained onset. The confirmatory signatures are dose-independent
post-onset slopes and plateaus, an apparent \(p_{50}\) that rescales with
horizon and effective neighborhood count, and a strict-ceiling change only in
branches with an established lineage.

All branches retain dual raw-group/update clocks and log every attempted
group, \(A\) candidate, defect seed, replayed lineage item, strict conversion,
and memory transition. This experiment can falsify the proposed singular
mechanism without first running a broad dose grid.

The legacy main-run checkpoints preserve sharded model and optimizer state,
scheduler/trainer progress, and orchestrator counters, but not a complete
snapshot of live in-flight queues and every process RNG. They are suitable for
a paired fresh-schedule withdrawal screen after terminal drain, not for a
claim of bitwise continuation from the historical trajectory. A confirmatory
fork must bind the new common schedule and all explicit sampling seeds rather
than describing the old checkpoint as an exact runtime clone.

A separate stateful-verifier hysteresis construction answers a different
question. After a common high-dose pulse, one can fork identical policies
while retaining versus resetting a lagged susceptibility state

\[
m_{b+1}=\tfrac12m_b+\tfrac12\widehat P_b(A),\qquad
p_b=\operatorname{clip}[p_0+0.10(m_b-0.11827),0,0.05].
\]

A Retain--Reset difference after five memory half-lives and a further fixed
dwell would identify verifier-state feedback; a difference that decays with
the half-life is only lag. Because this construction deliberately makes the
verifier endogenous, it must not be reported as evidence that the current
exogenous resampled-coin verifier has autonomous propagation.

## 7. Candid novelty matrix

“Yes” means the feature is an explicit controlled object, not merely present
incidentally.

| Study | Behavior-specific recipient | Strict process target | Near-zero strict-dead test | Raw/update dual clocks | Iterative SFT | Clipping isolated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Rad et al. 2026 | No; class-conditional | No | Support barrier noted, no dose experiment | No | No | No |
| Cai et al. 2025/26 | No; treated as assumption violation | No | No | No | No | No |
| Yang et al. 2026 | Active policy-realizable wrong labels | No | Explicit theoretical critical ratio | No | No | No |
| Egashira et al. 2026 | Yes; deterministic FP triggers | Oracle task correctness | Plateau/collapse regimes, no probability sweep | No | No | No |
| Zhang 2026 | Natural persistent code-verifier FPs | Hardened task correctness | Leaky versus hardened, five seeds | No | No | No |
| Khalifa et al. 2026 | Hack-contaminated selected traces | Held-out code correctness | 1.2% catalyst, not randomized | No | Yes, then RL | No |
| Shao et al. 2025/26 | Random/format rewards | No | Random \(p=0\) versus positive | No | No | Yes |
| Mitsuhashi et al. 2026 | Class-conditional FP/FN | No | Dose and rollout-count sweep | Compute, not paired clocks | No | No |
| Plesner et al. 2026 | Uncontrolled weak-verifier correlation | No | No | No | No | No |
| Li et al. 2026 | Feature-dependent preference noise | No | No | No | No | No |
| Helff et al. 2026 | Yes, deterministic shortcut | Analogous intensional target | No probability sweep | No | No | No |
| Che and Wu 2026 | Visible decision-relevant reward channel | Environment true utility | Reliability sweep with sharp finite response | No | No | No |
| Zhou 2026 | Candidate-conditioned judge blind spot | Exact-match hidden anchor | Stochastic basin entry across five seeds | Iterations, not paired clocks | Yes, self-play DPO | No |
| Pan et al. 2022 | Proxy-specific behavior | Environment true return | Capability threshold, not \(p\to0\) | No | No | No |
| Gao et al. 2022/23 | Reward-model proxy | Gold reward model | No; smooth scaling fits | Optimization strength | No | No |
| Uesato / Lightman / Wang | No injected defect | Yes | No | No | No | No |
| Current GSM-Infinite design | Yes: B/S/M/G/I decomposition | Yes | Yes, finite-bank OP21–40 gate | Yes | Fixed-count screen and planned iteration | Planned RL factorial |

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
- B/S/M/G recipient distributions can still differ on unmeasured features;
  frozen S retains the target behavior on 62.6%–64.9% of recipients and even
  the deterministic minimum M retains it on 10.1%–11.3%;
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
- **“Reduced behavior-recipient effect”** only if B differs reproducibly from
  S and the audited B-minus-S alignment exceeds the preregistered 20-point
  floor.
- **“Full-versus-minimum behavior-recipient effect”** only if B differs
  reproducibly from M and B-minus-M alignment exceeds the 80-point floor. M is
  the feasible within-group minimum, not a zero-behavior or otherwise
  distribution-matched control.
- **“Total allocation-mechanism effect”** if S differs reproducibly from the
  uniform global G control and the measured allocation moves accordingly.
- **“Prompt-allocation effect”** only if S differs reproducibly from
  \(G^\star\), which matches S's behavior-class recipient count, and the
  measured prompt/operation allocation moves accordingly. S--G alone also
  changes recipient composition and cannot identify this pathway.
- **“Practical iid optimizer effect”** if I differs from C0 despite \(J>0\),
  especially if clipping controls it.
- **“Finite-time crossover”** if the apparent critical dose moves with time,
  group size, or raw exposure as predicted by \(pht\) or \(Khp\).
- **“Autonomous defect-lineage propagation”** only if an \(A\)-rich
  checkpoint retains positive drift or a long-lived high state after changing
  only \(p\) to zero, and a paired pulse estimates post-seed offspring without
  conditioning away raw-time cost. Persistence of parameters alone is not
  enough.
- **“Absorbing-state perfection boundary”** only if autonomous propagation is
  supercritical, positive-dose runs differ in waiting time but agree
  conditionally in post-onset growth and plateau, and the apparent boundary
  follows the preregistered size/horizon scaling. At fixed finite size,
  stationary \(p\downarrow0\) returns to the clean absorbing state.
- **“Phase transition”** only with a stable nonanalytic/bistable signature:
  dose-to-zero separation that survives clock matching and longer horizons, or
  reproducible hysteresis at the same dose. A steep curve alone is not enough.

The evidence currently supports a narrower conclusion. Behavior-conditioned
false positives are theoretically capable of changing the selected behavior
distribution, and strict-dead fixed-count selection has an exact
zero-versus-positive support singularity. The RL data now identify the realized
finite-time mechanism: false positives activate otherwise zero-advantage hard
groups, rotate the curriculum, and change optimizer-update throughput. The
1% arm's earlier apparent raw-budget benefit reverses under an optimizer-step
AUC and has washed out at the longer raw clock, while the 5% arm is
substantially worse per update. This supports a smooth
\(1-e^{-128hp}\) group-activation crossover and a transient inverted-U
raw-budget pattern at earlier clocks, not an exponential final-ceiling effect.
No arm has yet solved unseen OP41–45,
so the runs establish neither a phase transition nor an altered asymptotic
ceiling. Within the constant-fitness replicator and first-order fixed-K null, a
sharp finite-time curve is not hysteresis; a reproducible same-dose basin
difference requires measured nonlinear state dependence or pre-existing
multi-basin dynamics. The preregistered B/S/M/G/I frozen-bank experiment is
designed to determine which part of any observed effect comes from recipient
identity, prompt allocation, global hard-sample support, or an iid noisy
channel. The clipping factorial, replicated RL seeds, longer strict
evaluations, and bidirectional iterative-SFT test remain necessary before
stronger practical GRPO, ceiling, or hysteresis claims. The new
defect-withdrawal screen is an earlier and cheaper gate for the stronger
absorbing-state hypothesis: if \(A\) decays when \(p\) alone is switched off,
then the current verifier has no \(p\)-independent propagation channel and its
near-zero response should be modeled as ordinary activation rather than a
perfection discontinuity.
