# Fresh-bank value-alias verifier-defect study

## Status and claim boundary

This document freezes `verifier-defect-alias-phase-v1` before any
study-specific model output is inspected. The experiment asks whether a small
verifier defect that is conditional on one exact model behavior can create
qualitatively different iterative-SFT dynamics when the same initial behavior
mass is diffuse across tasks or concentrated in one semantic cell.

The constructed defect is not random label noise. A strict-wrong completion is
accepted with probability `p` only when it has the prompt's exact declared
value-alias lineage `A*`. The primary performance endpoint is guarded strict
OP11--45 pass@1. Released strict dependency-graph pass@1 is retained for
comparison with earlier RSCI runs. A performance claim requires both metrics
and their disagreement rate; an improvement visible only under the permissive
released parser is a verifier-surface artifact.

Stage 0 estimates whether the seeded behavior transfers to fresh prompts. It
does not establish a phase transition. The six promoted rounds are a finite,
constructed phase-mechanism test, not evidence for a thermodynamic transition,
critical exponent, universal ceiling, or hysteresis.

No file in this directory authorizes a scheduler mutation. A launch requires a
commit-pinned source tree, complete immutable authority, protected dispatcher,
resource gate, explicit task IDs, and explicit study confirmation.

## Exact behavior and training surface

For every eligible prompt, `value_alias_intervention.py` creates one canonical
strict solution and one standardized `A*` solution. `A*` replaces exactly one
canonical dependency parent with a different earlier canonical parent having
the same scalar value. It must preserve the final answer and every node value,
change only the declared delete/add edge pair, remain acyclic and closed, and
have no independent arithmetic-execution issue.

A generated completion counts as `A*` only when it matches the prompt's exact
declared standardized solution surface, modulo whitespace and the exact
plain/XML envelope conversion. Prefix, mid-body, or suffix text; repeated
answers; residual assignments; arbitrary or unclosed tags; other graph defects;
and arithmetic issues are rejected. Broader natural alias families are
diagnostics and never drive selection.

The training conversation is byte-defined as

```text
user:      <question> {problem.strip()} {question.strip()} </question>
assistant: <solution>{body.strip()} </solution> <answer> {answer} </answer>
```

There is no space after `<solution>`. Eligibility binds the tokenizer, chat
template, incremental assistant mask, conditional EOS append, shifted input
count, and assistant loss-token count. Canonical and `A*` renders must both fit
2,048 model-input tokens and have exactly equal input and assistant-token
counts.

## Fixed-byte source authority

The prompt population is the exact OP21--40 tail of the fixed OP10--40
aggregate:

| Artifact | Rows/bytes | SHA-256 |
| --- | ---: | --- |
| Aggregate `train.jsonl` | 31,000; 379,684,908 | `59dd47898e1ba2e348f23c080b58f354ea56ea15a7bc39c33ac96aea5335afd8` |
| `dataset_manifest.json` | 20,547 bytes | `33ea14662ef788e3a2172444714b4733a8f43da8605889a48b77a60fa039b084` |
| `audit.json` | 2,167 bytes | `db9ee735ccff23c4daea1f0ff5e50ea09843228c5b2181cbf4ae289b97e7bb1f` |
| Exact OP21--40 byte tail | 20,000; 279,934,980 | `54c00e6782d526edab1a417b470f040763a16e7b4c9c8d9731738a83b01d7a73` |

The byte range is `[99,749,928, 379,684,908)`. Materialization independently
reconstructs it from the 20 pinned per-operation sources and revalidates the
source before and after selection. This is a strong fixed-byte authority but
not full historical generation provenance: the original uncommitted generator
and prime-rl commit were not bound by the aggregate manifest. Reports must keep
`generation_provenance_complete=false` and condition claims on these bytes.

The eligibility cascade is fixed:

| Stage | Rows |
| --- | ---: |
| Validated single-edge value alias | 19,536 |
| Both renders fit 2,048 | 19,456 |
| Exact input/assistant length equality | 13,887 |

Materialization protocol is `value-alias-disjoint-bank-v1`, seed `20260809`.
The cluster cell remains the previously hash-selected
`teachers_in_school/normalforward` cell under
`value-alias-iterative-sft-v1`; changing the bank protocol does not reselect the
mask.

## Eight disjoint fresh-prompt banks

The 13,887 eligible prompts deterministically form eight mutually disjoint
banks. Each bank has:

- 1,536 prompts;
- 256 prompts in each of the six template×mode cells;
- 76 prompts in four operations and 77 in sixteen operations;
- 12 or 13 prompts in every operation×template×mode stratum;
- at least one unused eligible prompt retained in every stratum.

Within every optimizer step, the schedule contains 16 distinct operations.
Exactly 64 of the 96 steps contain three mask prompts and 32 contain two, for
256 mask prompts total. Every prompt becomes an adjacent canonical/alias row
pair, so a pair is contained in one four-row microbatch.

Bank use is immutable:

| Bank | Use |
| ---: | --- |
| 0 | Stage-0 soft-mixture training only |
| 1 | Stage-0 teacher readout; promoted round 1 training |
| 2--6 | Readout of the previous teacher; promoted rounds 2--6 training |
| 7 | Final `T6` readout only; never training |

Thus every trained-on prompt is first observed under a teacher that has never
seen it, no prompt is used for training twice, and every post-training mechanism
readout is on a fresh bank. Exact bank, prompt, opportunity, token-count,
schedule, quota, and weight hashes are frozen in the write-once materializer
manifest and copied into the launch authority.

## Stage-0 causal initialization

Let

\[
x=\frac{34}{1536}=\frac{17}{768},\qquad
\alpha=\frac{256}{1536}=\frac16,\qquad
y=\frac{x}{\alpha}=\frac{17}{128}.
\]

One common 3,072-row Parquet contains both target surfaces for all 1,536 bank-0
prompts. The three arms read the same messages, rows, ordering, prompt pairs,
and token counts; only the selected scalar weight column differs. For prompt
`i`, assistant length `L_i`, and target mixture masses `(m_C,m_A)`, the two SFT
weights are `(m_C/L_i,m_A/L_i)`. Consequently every prompt contributes exactly
one unit of assistant-token mass.

- Strict: `(m_C,m_A)=(1,0)` for every prompt.
- Diffuse: `(m_C,m_A)=(1-x,x)` for every prompt.
- Clustered outside the mask: `(m_C,m_A)=(1,0)`.
- Clustered inside the mask: `(m_C,m_A)=(1-r_i x,r_i x)`.

The deterministic integer multipliers satisfy

\[
4\le r_i\le9,\qquad
\sum_{i\in b}r_i=16\quad\text{for every optimizer step }b,
\qquad
\sum_{i:\operatorname{op}(i)=o}r_i=N_o.
\]

They are obtained by a deterministic integral max flow after fixing the
operation/step graph. Therefore diffuse and clustered arms have exactly the
same rational design margins before trainer float32 quantization:

\[
\text{alias mass per step}=16x=\frac{17}{48},
\qquad
\text{alias mass in OP }o=N_ox,
\qquad
\text{total alias mass}=34.
\]

The clustered local mean is `17/128`; its maximum prompt mass is
`9x=51/256<0.2`. A constant mask weight cannot simultaneously match step and
operation margins, so the frozen integer construction is part of the treatment
definition. The manifest also replays the actual float32 token weights and
records prompt-pair, step, operation, and total deviations. Runtime equality is
reported to those measured tolerances, never described as mathematically exact.

Each arm starts from the exact original base checkpoint and a fresh optimizer:

```text
seq_len             = 2048
pack_function       = fixed_stack
batch_size          = 32 rows = 16 prompt pairs
micro_batch_size    = 4 rows = 2 prompt pairs
shuffle             = false
weight_column       = {strict,diffuse,clustered}_sft_weight
loss_impl           = torch
optimizer           = AdamW
learning_rate       = 1e-4
scheduler           = constant
max_steps           = 96
examples consumed   = 3072, exactly one pass
GPUs                 = 1
```

Optimizer betas, epsilon, decay, clipping, model fields, checkpoint settings,
package versions, base/tokenizer inventories, and resolved configs must be
bound before launch. `optimization_dtype` and `reduce_dtype` retain their
existing defaults.

## Frozen candidate clock and inference contract

Every mechanism readout uses exactly 128 separate `n=1` requests per prompt.
Collection never stops after two hits. For domain `d`, replicate `q`, round
`r`, prompt key `i`, and rank `j`, hash the UTF-8 NUL-delimited material

```text
verifier-defect-alias-phase-v1\0{d}\0{q}\0{r}\0{i}\0{j}
```

and interpret the first eight SHA-256 bytes as unsigned big-endian `R`. The
request seed is `R(candidate-seed) % (2**63 - 1)`; the verifier draw retains
the full uint64 `R(verifier-draw)`. Dose, topology, generated text, and behavior
label are absent, so dose masks are nested and request slots are arm-invariant
whenever the model identity is the same.

The prior RO-compatible sampling values are `max_tokens=2048`,
`temperature=0.7`, `top_p=1.0`, `top_k=-1`, stop `['</answer>']`,
`skip_special_tokens=false`, and `n=1`. Before collection, the authority must
also bind every resolved/default min-p, penalty, EOS, stop-ID, renderer,
extraction, retry, engine, dtype, tensor-parallel, context-limit, and server
field. The pinned environment is vLLM `0.22.0+cu129`, transformers `5.6.2`,
and openai `2.38.0`, unless the final authority explicitly freezes a different
fully reproduced environment before any output is observed.

Retries preserve prompt, rank, and seed. Duplicate/conflicting keys fail
closed. Finish reason, generated-token count, context length, stop reason, and
truncation are stored. Truncation is a valid negative model outcome, never
silently dropped.

## Stage-0 readout and continuation

After all three Stage-0 teachers complete, each is collected on fresh bank 1:
`1,536*128=196,608` exact records per teacher. Define

\[
Z_{aij}=\mathbf1[\text{candidate }(a,i,j)\text{ is exact guarded }A^*],
\qquad
\hat z_{ai}=\frac1{128}\sum_j Z_{aij}.
\]

Stage-0 prevalence, topology contrast, loss, strict accuracy, and theoretical
map values are descriptive. They do not determine continuation and cannot be
used to retune the mask, mass, bank split, thresholds, or doses under this
study ID. Continuation authority is issued only from integrity facts:

1. source, implementation, model, config, and environment authorities match;
2. all bank memberships, schedules, token counts, and consumed float weights
   replay exactly;
3. each trainer completed exactly 96 steps from the declared base with fresh
   state and a stable checkpoint;
4. collection has exactly one validated row for every prompt/rank key;
5. seed, classifier, full-consumption, and dose-nesting test vectors replay;
6. no input or output was overwritten, quarantined, or ambiguously resumed.

There is no promotion gate on `A*` rate, sign, confidence interval, `F2`, loss,
or strict accuracy. If the initialization manipulation is weak or reversed,
that is a result, not a reason to select a new seed.

## Promoted six-round experiment

Only the diffuse and clustered Stage-0 teachers branch over
`p in {0,0.01,0.025,0.03,0.05,0.10,0.20}`. The 2.5% and 3% probes bracket the
idealized scalar saddle near 2.61%; they do not assume that the vector/fresh-bank
system shares that threshold. The 20% arm is a saturation control. For round
`r=0,...,5`, teacher `T[r]` is collected on fresh bank `r+1`. For prompt `i`, define

\[
A_i^{(r)}(p)=
\mathbf1\!\left[
\sum_{j=0}^{127}Z_{ij}^{(r)}
\mathbf1[U_{ij}^{(r)}\text{ passes }p]\ge2
\right].
\]

For exact dose `a/b`, a slot passes iff

```text
verifier_draw_uint64 * b < a * 2**64
```

The raw candidate bank is classified once and swept over all doses. Every
receipt stores ranks `0..127`, all request seeds and verifier draws, exact and
accepted `A*` ranks, hit count, selected target, and target-pair identity.

The selected bank remains a common adjacent canonical/alias pair dataset. If
`A_i=1`, its weights are `(0,1)`; otherwise they are `(1,0)`, each divided by
the prompt's assistant-token count. Thus every prompt retains unit mass and
every round remains one exact 96-step pass. Sampled candidate text is never
trained directly. Every `T[r+1]` resets to the original base weights and fresh
AdamW state; the previous teacher supplies candidates only.

The Stage-0 bank-1 collection is reused as round-0 input only after exact
identity validation. Bank 7 is final readout only. Physical outputs may be
aliased only after proving complete equality of model, bank, seeds, sampling,
config, and selected weights.

## Vector theory and phase diagnostic

For true prompt-level `A*` prevalence `z_i`, the two-hit probability is

\[
F_2(z_i;p)=1-(1-pz_i)^{128}-128pz_i(1-pz_i)^{127}.
\]

The correct expected selected fraction is

\[
S_p(\mathbf z)=\frac1N\sum_i F_2(z_i;p),
\]

not `F2(mean(z);p)`. At small `pz`,

\[
S_p(\mathbf z)\approx {128\choose2}p^2\mathbb E[z^2]
= {128\choose2}p^2\bar z^2(1+\mathrm{CV}^2).
\]

Thus prompt/feature heterogeneity can amplify selection even at fixed global
prevalence. The former scalar unstable-separator gate and predictions obtained
by iterating `F2(mean(z))` are invalid and removed.

At every teacher report the mean, variance, second moment, histogram,
participation ratio `(sum z)^2/sum(z^2)`, `S_p(z)`, mean-field value, their
heterogeneity gap, exact realized recipients, and global/cell/operation/mask
breakdowns. With fresh banks the unknown learning transition is a
generalization operator

\[
\mathbf z^{(r+1)}=G_r(\mathbf A^{(r)}),
\]

which is measured rather than assumed. The qualitative hypothesis is that a
small conditional defect can sustain a transferable semantic-cell behavior
while an equal-mass diffuse seed decays, producing a sharp dose/topology
interaction. All completed arms are reported if the hypothesis fails.

## Held-out OP11--45 evaluation

Evaluate `T0` through `T6` on the frozen 7,000-prompt suite. Raw IDs are not
unique, so every join and seed uses
`(operation,row_index,prompt_sha256)`. Prove zero canonical-prompt-byte overlap
with all eight training/readout banks.

Report:

- guarded strict pass@1 as the primary performance endpoint;
- released strict dependency-graph pass@1 for historical comparison;
- answer-only correctness and released-minus-guarded discrepancy;
- full-consumption failure codes and corruption rate;
- OP11--14, OP15--20, OP21--40, OP41--45, and per-operation results;
- paired prompt differences from the same-topology `p=0` arm;
- output/context length p50, p95, p99 and truncation rate.

The guard uses an anchored plain/XML envelope, a reference-locked residual
skeleton, clean deterministic execution, and an ASCII arithmetic lexical gate.
It rejects ignored prefix/mid/suffix text, repeated answers, residual equations,
unknown/malformed tags, and truncated structure. Released strict is not
changed. Because the guard intentionally rejects unconventional graph-equivalent
paraphrases, both metrics and their disagreement are always visible.

Uncertainty uses one authority-pinned paired prompt-cluster bootstrap. Candidate
ranks remain within prompt clusters. Bands are descriptive and never control
continuation.

## Receipts, restart semantics, and resources

Every task has immutable intent before submission, an exact scheduler comment,
captured submitted script, protected submission receipt, and terminal receipt.
SFT success requires `COMPLETED/0:0`, `Restarts=0`, exactly 96 trainer updates,
the declared dataset/weight column, and a stable final checkpoint. Failed SFT
restarts from step zero in a fresh attempt directory. Candidate collection may
resume only missing keys under an identical authority. CPU selection and
analysis are content-addressed, write-once, and independently replayed.

Future tasks remain local; they are not parked in Slurm behind dependencies.
Resource waves are:

1. finish and replay all CPU artifacts;
2. at most three one-GPU Stage-0 SFT jobs;
3. at most two Stage-0 candidate collectors;
4. local integrity analysis and continuation authority;
5. for each promoted round: at most two collectors, local selection, then at
   most four SFT/evaluation jobs, followed by a complete round barrier.

The study cap is four live GPUs counting running and resource-ready pending
tasks. Existing unrelated group use counts against the scheduler gate. A
persistent `QOSGrpGRES`, unresolved intent, live duplicate, or unavailable
protected control socket refuses submission. No round `r+1` task is
materialized before every required round-`r` receipt exists.

## Claim limitations

- This is one model, fixed bank partition, seed, behavior, mask, candidate
  clock, and six-round horizon.
- Diffuse versus `teachers_in_school/normalforward` is a semantic-cell
  correlation treatment, not a cell-invariant concentration effect. Replication
  over the other five cells and matched random masks is required before making
  a generic topology claim.
- There is no matched behavior-independent recipient control, so this study
  alone cannot distinguish prompt alignment from an equal corruption burden. A
  deterministic recipient-permutation placebo matched on target count,
  operation, and optimizer step is required for that claim.
- One training seed, mask, and bank partition do not estimate training-run or
  mask variance; prompt bootstrap cannot supply either source of uncertainty.
- Fresh banks remove exact prompt lookup; they do not prove transfer outside
  GSM-Infinite or this operation/template family.
- `p` is conditional on exact guarded `A*`, not the marginal verifier
  false-positive rate.
- Standardized oracle targets and base-reset iterative SFT differ from ordinary
  on-policy RL and warm-start self-training.
- Exact-128 readouts are finite-sample measurements; candidate independence and
  exact target-to-model transfer are not assumed.
- Guarded strict is conservative; released strict is permissive. Neither may be
  silently substituted for the other.
- A finite dose grid can show a sharp, reproducible regime change but cannot by
  itself establish a thermodynamic phase transition or hysteresis.
- A proxy/alias increase without the strict OP11--45 endpoint is mechanism
  evidence, not a performance improvement.
