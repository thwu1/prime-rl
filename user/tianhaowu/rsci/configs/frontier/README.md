# Iterative frontier SFT configs

The two production tracks start at op11 and advance one operation at a time:

- `answer_correct.toml` retains every sampled trajectory with the correct final
  answer, even when its dependency graph is wrong.
- `strict_correct.toml` retains only trajectories accepted by the released
  strict dependency-graph scorer. As in the released scorer, all gold nodes,
  values, dependencies, and the final answer must match; extra predicted nodes
  are allowed.

For each frontier operation, the teacher samples 128 completions per generated
prompt until exactly 50,000 trainable accepted trajectories are selected. More
than one accepted completion from a prompt may enter the shard. The shard is
added to every earlier 50K shard in that track, and a new model is trained for
one packed epoch from the fixed original op2-10 pretrained checkpoint. The
newly trained model becomes the teacher for the next operation.

Each operation also collects 5,000 accepted validation trajectories from a
deterministic prompt stream disjoint from the 50K training stream. It uses the
same operation, generator distribution, teacher, sampling, and track filter.
These held-out shards accumulate across operations but never enter training.
Validation and weight checkpoints occur at matched intervals; the stable
checkpoint with minimum held-out token-weighted loss is selected (earliest
step breaks an exact tie), post-evaluated, and used as the next teacher.

The answer track advances only while answer-only pass@1 is above 1%; the strict
track uses strict-graph pass@1. Both answer and strict pass@1, 2, 4, 8, 16, 32,
64, and 128 are stored for every evaluation.

Production inference/evaluation jobs allocate four H100 nodes. Each node runs
an independent eight-GPU data-parallel server, and a round-robin router fronts
the four replicas. The runtime config multiplies `max_concurrent_prompts` and,
for collection, `prompt_batch_size` by the allocated node count (16 to 64 in
the production configs). Prompt generation, 128 samples per prompt, verifier
logic, deterministic ordering, and exact accepted-trace trimming are
unchanged. The immutable source configs remain under `iterations/opN/configs`;
the routed runtime configs are preserved under each phase's `runtime/`
directory and snapshotted under `configs/` with their hashes.

The per-node concurrency was measured with the production request shape
(`n=128`, 2,048-token cap) rather than inferred from HTTP request counts.
Concurrency 16 is the validated per-node setting: 16 prompt requests × 128
choices fills 2,048 active sequences, equal to eight engines ×
`max_num_seqs=256`. A four-node job therefore uses 64 prompt requests and up
to 8,192 active sequences in aggregate. Higher prompt concurrency only adds
queueing and reduced measured token throughput.

Released validation files end at op20. The production configs continue through
op30 using a deterministic generated evaluation extension under
`generated_validation_data_dir`. Because the OP30 answer gate remains above
1%, `answer_correct_op40.toml` and `strict_correct_op40.toml` define the next
OP31-40 extension with `generator_op_max=40`. OP31 was smoke-tested to produce
an exact 31-operation graph before activating this extrapolated range. Both
extensions use seed 20260802, equal weights over all three templates and both
generation modes, and 200 unique prompts per operation. Each generated file
has a sidecar manifest with its source manifest, hashes, generation settings,
rejection counts, and exact template/mode counts. The per-round held-out audit
also proves that generated evaluation prompts overlap neither the 50K training
prompt stream nor the 5K validation-loss prompt stream.

The answer track remains well above 1% at OP34, so
`answer_correct_op50.toml` predefines the OP41-50 continuation with
`generator_op_max=50`. It changes only the allowed extension fields and is not
activated until the OP40 watcher exits with `max_operation_exhausted`; generated
evaluation files remain deterministic and are materialized on demand.

The generator's exact-operation acceptance is non-monotonic beyond OP50, so
OP51-60 is split into empirically validated generator envelopes:

| Config | Operations | `generator_op_max` |
| --- | --- | ---: |
| `answer_correct_op55.toml` | OP51-55 | 75 |
| `answer_correct_op58.toml` | OP56-58 | 90 |
| `answer_correct_op59.toml` | OP59 | 95 |
| `answer_correct_op60.toml` | OP60 | 100 |

For each range, six-cell smokes cover all three contexts and both generation
modes at both endpoints (or the sole operation). Every smoke uses the production
10,000-attempt-per-sample bound. A persistent waiting handoff observes the
watcher launched by the preceding extension and activates the next range only
after `max_operation_exhausted`; it exits unchanged at the 1% frontier.

To extend a state that exhausted its configured range, archive and activate
the config for the next range before relaunching its watcher. For OP31-40:

```bash
uv run --no-sync user/tianhaowu/rsci/frontier_extend.py \
  user/tianhaowu/rsci/configs/frontier/answer_correct_op40.toml
uv run --no-sync user/tianhaowu/rsci/frontier_extend.py \
  user/tianhaowu/rsci/configs/frontier/strict_correct_op40.toml
```

For a long-running track, schedule the next extension as an `afterany`
dependency on the current persistent watcher. The handoff exits successfully
without launching anything if the track reaches the 1% stopping frontier. It
extends and submits the next watcher only when the previous range ends with
`max_operation_exhausted`; any failed or inconsistent state exits nonzero for
manual diagnosis. For the answer OP41-50 range:

```bash
sbatch \
  --dependency=afterany:<current-watcher-job-id> \
  --job-name=rsci-answer-op50-extension \
  --output=/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/answer-correct/extension-op50-%j.log \
  user/tianhaowu/rsci/scripts/run_frontier_extension.sbatch \
  user/tianhaowu/rsci/configs/frontier/answer_correct_op50.toml
```

When the dependency is an extension job that will launch the next watcher, use
the waiting handoff. For OP51-55 after the OP41-50 extension:

```bash
sbatch \
  --dependency=afterany:<op50-extension-job-id> \
  --job-name=rsci-answer-op55-extension-wait \
  --output=/checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/answer-correct/extension-op55-%j.log \
  user/tianhaowu/rsci/scripts/run_frontier_extension_wait.sbatch \
  user/tianhaowu/rsci/configs/frontier/answer_correct_op55.toml
```

Chain the OP58, OP59, and OP60 waiting handoffs in the same way, each depending
on the preceding handoff job. The waiting handoff fails rather than extending
if state says `running` but the expected watcher has disappeared, preserving
failures for diagnosis.

The upgrader permits only the higher maximum and generated-evaluation fields;
all training, filtering, sampling, optimization, and validation-loss settings
remain frozen. It preserves the prior state/config before resuming at the next
operation.

Launch the persistent CPU watchers from a visible tmux `Launcher` window:

```bash
bash user/tianhaowu/rsci/scripts/run_frontier.sh \
  user/tianhaowu/rsci/configs/frontier/answer_correct.toml
bash user/tianhaowu/rsci/scripts/run_frontier.sh \
  user/tianhaowu/rsci/configs/frontier/strict_correct.toml
```

The watcher requests 128 GB of CPU memory. Cumulative parquet construction
loads the accepted shards in memory and requires more than 32 GB at 1.25
million rows; 128 GB covers the planned continuation through OP50.
If a watcher is interrupted during dataset construction, verify that neither
the parquet nor its manifest exists before resuming the same config. Completed
collection manifests remain authoritative and are not regenerated.

The `smoke_*` configs run the same end-to-end state machine with 128 training
traces, 64 held-out traces, two evaluation prompts, and one operation. They are
wiring checks, not scientific measurements.

The strict OP25 exponential-replay ablation keeps the λ=1 production loop
unchanged and reuses its immutable OP11-25 accepted shards. For operation `i`
at frontier `n`, row weight is `lambda ** (n - i)`. Deterministic permutation
cycles materialize exactly the same 750K train and 75K held-out row totals as
the baseline; SFT also keeps the baseline 1,144-step compute budget. Separate
λ=0.95 and λ=0.90 CPU watchers build the datasets, reset from the same base,
select minimum reweighted held-out loss, and evaluate OP25 and OP26.

Each experiment root contains `state.json`, an append-only `STATUS.md`, and:

```text
iterations/opN/
├── configs/                 # immutable inference/eval/collection/SFT TOMLs
├── pre_eval/metrics.json    # frontier gate and pass@1..128
├── collection/              # prompts, all generations, exact accepted shard
├── validation_collection/   # disjoint same-distribution accepted shard
├── held_out_audit.json      # distribution match and zero prompt overlap
├── cumulative_dataset/      # prior shards + opN shard and manifest
├── cumulative_validation_dataset/
├── model_min_val/weights/   # all matched stable checkpoint candidates
├── checkpoint_selection.json
└── post_selected_eval/      # selected checkpoint's in-distribution metrics
```

Collection and evaluation JSONL files resume by prompt/sample rank. The watcher
records each child SLURM job before waiting, treats result artifacts as the
completion authority, and is safe to requeue.

Regenerate the progress figure from whatever completed artifacts are currently
available with:

```bash
uv run user/tianhaowu/rsci/plot_frontier.py \
  --answer-root /checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/answer-correct \
  --strict-root /checkpoint/ram-h100-2/tianhaowu/rsci/frontier-sft/strict-correct \
  --output user/tianhaowu/rsci/figures/frontier_progress.svg
```
