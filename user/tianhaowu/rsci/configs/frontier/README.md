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

The answer track advances only while answer-only pass@1 is above 1%; the strict
track uses strict-graph pass@1. Both answer and strict pass@1, 2, 4, 8, 16, 32,
64, and 128 are stored for every evaluation.

Launch the persistent CPU watchers from a visible tmux `Launcher` window:

```bash
bash user/tianhaowu/rsci/scripts/run_frontier.sh \
  user/tianhaowu/rsci/configs/frontier/answer_correct.toml
bash user/tianhaowu/rsci/scripts/run_frontier.sh \
  user/tianhaowu/rsci/configs/frontier/strict_correct.toml
```

The `smoke_*` configs run the same end-to-end state machine with 128 accepted
traces, two validation prompts, and one operation. They are wiring checks, not
scientific measurements.

Each experiment root contains `state.json`, an append-only `STATUS.md`, and:

```text
iterations/opN/
├── configs/                 # immutable inference/eval/collection/SFT TOMLs
├── pre_eval/metrics.json    # frontier gate and pass@1..128
├── collection/              # prompts, all generations, exact accepted shard
├── cumulative_dataset/      # prior shards + opN shard and manifest
├── model/weights/step_K/    # preserved trained HF checkpoint
└── post_eval/metrics.json   # in-distribution score after opN training
```

Collection and evaluation JSONL files resume by prompt/sample rank. The watcher
records each child SLURM job before waiting, treats result artifacts as the
completion authority, and is safe to requeue.
