# RL configs

`op11_20_strict_grpo_r128.toml` starts from the released composition-pretrained
base and uses 128 on-policy rollouts per GSM-Infinite problem. Its only
optimization reward is the released strict dependency-graph check. Answer
correctness and the executable strict grader are logged with zero reward
weight.

Generate the fresh, balanced 2K OP11–20 prompt pool first:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch user/tianhaowu/rsci/scripts/prepare_rl_op11_20.sbatch
```

The wrapper writes `audit.json` only after checking exact per-operation counts,
unique prompt and sample IDs, all canonical completions under the strict
verifier, and zero prompt overlap with the released OP11–20 validation shards.

Validate and materialize the five-node SLURM launch without submitting it:

```bash
bash user/tianhaowu/rsci/scripts/run_rl_op11_20.sh \
  user/tianhaowu/rsci/configs/rl/op11_20_strict_grpo_r128.toml \
  --dry-run
```

Remove `--dry-run` to submit. The allocation uses one eight-GPU training node
and four one-node inference replicas. The 8,192-rollout in-flight cap is 64
problem groups, matching the measured optimum of 16 concurrent 128-rollout
groups per inference node.

The training pool is disjoint from the released OP11–20 validation shards.
During RL, each operation is evaluated separately with one rollout per held-out
problem every 25 updates. Use the existing RSCI evaluation pipeline for the
final 128-rollout pass@k comparison.
