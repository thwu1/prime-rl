# Known-cost verifier-defect boundary pilot

Status: design and pre-RL decision rules frozen; no known-cost RL job submitted.
Corrected v2 kernel job `10278600`, its validator, and its receipt finalizer are
pending with zero runtime. The tagged-bank and runtime-law preflights pass, but
the kernel execution receipt remains mandatory before any RL launch.

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

## Post-kernel provenance amendment (2026-08-08)

This amendment changes no scientific intervention, arm, gate, spending rule,
or readout. Slurm retains controller batch-script bytes for only
`MinJobAge=600` seconds and has no job-script archive; after purge,
`scontrol write batch_script JOB -` returns empty stdout with exit code zero.
The immutable kernel execution receipt was written by the pinned finalizer
inside the retention window and that allocation completed its explicit
`validate --verify-scheduler` command, but a later launch-side attempt to fetch
the same ephemeral bytes cannot be a durable gate.

Before launch-intent materialization, freeze one adjacent read-only
`kernel_finalizer_reconciliation.json`. It must require the nonempty read-only
script captured directly from finalizer job `10281828` inside that job's
600-second controller-retention window, bind the exact allocation log, and
exact-match every retained GPU/validator terminal `sacct` field except
`submitted_batch_script_sha256`. The omitted live
field is not waived: the sidecar must statically replay the receipt with its
recorded historical finalizer, which independently binds both submitted-script
hashes to the pre-execution witness. Receipt mtime must fall after GPU and
validator completion and within the successful finalizer allocation. The
receipt is not modified. The launch intent and all later validators consume
only the immutable reconciliation, so an empty post-purge response is never
accepted as script evidence.

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
ordering check above passes, proceed with the full grid. Otherwise run only the
paired G/T doses `p={0.0125,0.0375}` in one block. Expansion from that smoke
screen is governed solely by the quantitative same-dose rule below; qualitative
selected--unselected separation or nonlinear specialization cannot override it.
Retain the measured high-K first-order result without relabeling it as localized
initialization, regardless of the spending decision.

The smoke-to-grid spending rule is fixed before observing the kernel or any RL
outcome. On the same-source tagged OP21--40 readout, let

\[
L_{a,p,c}=\frac{1}{N}\sum_i\left[
\frac{1}{2}\sum_{k\in S} A_{i,k}
-\frac{1}{4}\sum_{k\notin S} A_{i,k}\right],
\qquad
D_{p,c}=L_{T,p,c}-L_{G,p,c},
\]

where `A` is answer-correct/strict-wrong pass@1, `S` is the block's two
reference-selected tags, and `c` is a clock target. Proceed from the four-arm
smoke screen to the full grid iff at least one of the two smoke doses has
`D_p,c >= 0.02` at all four `T`/`2T` targets: optimizer steps `375` and `750`
and finalized raw groups `3000` and `6000`. Raw-clock values use the frozen
linear interpolation between the two retained exposure brackets when no exact
checkpoint exists; endpoints remain reported and are never relabeled as the
target. Otherwise stop the expansion.

The two-percentage-point floor is a practical localization screen, not a
confidence threshold or evidence of a phase transition. For 4,000 OP21--40
source prompts it is roughly twice the conservative independent-Bernoulli
standard error of the T-minus-G contrast; prompt and training dependence make
that calculation descriptive only. Report both doses, all operation bands,
strict accuracy, answer-wrong prevalence, and all endpoint values regardless
of the spending decision. No p-value or phase-transition claim is licensed by
this rule.

## Post-run authority and evaluation execution

The result-analysis and evaluation-execution implementations must be frozen in
a separate commit-pinned source snapshot before any known-cost RL arm starts.
After the kernel chooses the full-30 or smoke-4 branch and the immutable launch
intent exists, but while the original Stage-1 dispatch lock is held and every
one of the 30 frozen job identities has no current or 30-day accounting record
and no runtime start marker, materialize one adjacent
`postrun_authority.json`. The authority must:

- replay the launch intent with the exact historical validator recorded by that
  intent rather than a validator imported from the newer snapshot;
- bind the historical eval planner and the newer deterministic result analyzer,
  training-attempt replay, training readout consumer, completion-receipt
  materializer, exact sidecar-enforcing Stage-1 dispatcher, eval runner, and protected eval
  dispatcher by path, byte count, and SHA-256;
- cover the exact kernel-selected arm partition while checking all 30 frozen
  scheduler identities and output directories for pre-RL absence;
- be canonical, read-only, self-hashed, write-once, and required by guarded
  Stage-1 dispatch, result analysis, and eval dispatch. The recorded Stage-1
  dispatcher itself validates the adjacent authorities under its dispatch lock;
  there is no delegating wrapper path.

Every Stage-1 run must then receive a separate immutable completion receipt
that chains its protected submission to exact terminal `COMPLETED/0:0`
accounting, allocation stdout/stderr, clean orchestrator markers, both ledgers,
local event streams, resolved configs, and its final stable checkpoint. This
receipt proves scheduler and logical completion, not scientific metric
correctness, a normal trainer exit record, or a W&B exit record.

For a smoke-4 decision, the separate promotion authority additionally freezes
the exact remaining-26 partition and the spending rule above under the same
Stage-1 lock. It cannot authorize any of the four initial smoke arms. A passing
smoke result permits only an append-only Stage-2 intent for those 26 arms; it
does not alter the initial intent or retroactively change the screen.

Checkpoint evaluation uses the historical planner recorded by the launch
intent, then a separately pinned one-H100 runner. Each task evaluates exactly
one stable checkpoint through one untagged and six paired-tag OP11--45 shards,
writes a contiguous terminal receipt, and resumes only incomplete shards.
Protected dispatch is capped at five live jobs study-wide, strips every ambient
`SBATCH_*` variable, passes comment/QoS/account explicitly, and runs only from
the recorded control tmux. A scheduler-terminal attempt without a runner
receipt may be terminalized as failure for retry, but never synthesized as
success. Final analysis additionally requires the pinned dispatcher to bind
every terminal receipt to its immutable submission, exact submitted script,
and terminal allocation state/exit code; the historical generic receipt check
alone is insufficient.

## Readouts and decision rules

At every common clock report, overall and by all six tags:

- strict dependency-graph accuracy;
- answer-correct/strict-wrong A prevalence;
- answer-wrong prevalence, which detects tax evasion without strict repair;
- candidate count `C`, defect count `H`, gate exposure, proxy histogram, and
  negative-reward rate; and
- raw-groups per optimizer update.

Trainer entropy, mismatch KL, DPPO masked fractions, and gradient norm are
joint-batch statistics and are reported overall at the matching optimizer
clock. They are not attributed to neutral tags: token export is disabled, the
persisted trainer shards do not retain task/group identity, and gradient norm
is non-additive. Any table must mark per-tag trainer stability as unavailable
rather than impute it. Exact stale off-policy cancellations are reported
overall and by tag only when their synthetic group ledger rows retain a
deterministic `task_idx` mapping; joint-stop drain cancellations are overall
only because they never enter a finalized group. For a raw-group target that
falls between updates, report the exact group-prefix mechanism counts plus the
lower and upper trainer-metric endpoints; do not label an interpolation as an
exact raw-clock stability measurement.

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
