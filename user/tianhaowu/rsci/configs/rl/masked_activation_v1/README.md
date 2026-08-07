# Masked-activation Stage 1

This directory preregisters the 21-run Stage-1 matrix. It has not been
launched. The scientific estimands, clocks, uncertainty limits, and decision
rules are fixed in [PREREGISTRATION.md](PREREGISTRATION.md). Resolve each run
by composing, from left to right:

1. `../op10_40_strict_grpo_r128_defect_p00.toml`;
2. `common.toml`;
3. exactly one `s<seed>_<condition>.toml` run overlay.

Do not resolve or launch these runs from the live checkout. For each run, first
commit the complete intended runtime source, then create, materialize, and seal
its immutable snapshot with the three config paths in that order:

```bash
RUN_DIR=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-masked-activation-v1/seed-20260805/b-l128-p00125
SOURCE_COMMIT=$(git rev-parse HEAD)
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create \
  "$RUN_DIR" --commit "$SOURCE_COMMIT"
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" materialize-launch \
  "$RUN_DIR" \
  user/tianhaowu/rsci/configs/rl/op10_40_strict_grpo_r128_defect_p00.toml \
  user/tianhaowu/rsci/configs/rl/masked_activation_v1/common.toml \
  user/tianhaowu/rsci/configs/rl/masked_activation_v1/s20260805_b_l128_p00125.toml
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" seal-launch \
  "$RUN_DIR"
```

Submit only the sealed, materialized `rl.sbatch`. Every run overlay sets
`slurm.project_dir` to its own snapshot and runs
`activate_source_snapshot.sh "$OUTPUT_DIR"` before proxy and cache setup.
Submission is gated on the current fixed-clock SFT screen releasing the shared
200-GPU group budget. Each arm requests five 8-GPU nodes, so never admit more
than five arms concurrently even when the budget is otherwise empty. Submit
from the protected control tmux only:

```bash
tmux -S /tmp/codex-rsci-control-20260806.sock send-keys \
  -t codex-rsci-control-20260806:Launcher \
  "env -u SBATCH_OUTPUT -u SBATCH_ERROR sbatch --parsable --qos=h100_ram_high --account=ram $RUN_DIR/rl.sbatch" C-m
```

Record the returned job ID against the run directory before submitting another
arm. Do not submit this matrix while the SFT jobs are still quota-pending.

The common overlay fixes the physical group at 128 rollouts, the assembled
batch at 512 rollouts, writes a checkpoint every 25 updates and permanently
keeps every 50-update checkpoint, saves the exact train-group audit trail, and
drains once both 1,500 updates and 12,000 groups have been observed at a
50-update retained-checkpoint boundary. It stops scheduling new training groups
at the 20,000-group guard and disables asynchronous evaluation through the
3,000-update guard. Each run overlay replaces the complete training environment
list and pins the inference seed to the same value as the defect seed. The
orchestrator prompt shuffle remains the framework's common fixed seed 42 across
all arms; the three replicates vary generation and verifier randomization, not
prompt order. Output directories, source-snapshot project directories, Slurm
job names, and W&B names and tags are unique.

Each seed contains these seven conditions:

| Label | Assignment | Masked slots `L` | False-positive rate `p` |
| --- | --- | ---: | ---: |
| `c0_l128_p0` | behavior | 128 | 0 |
| `b_l128_p00125` | behavior | 128 | 0.125% |
| `b_l32_p005` | behavior | 32 | 0.5% |
| `b_l128_p0025` | behavior | 128 | 0.25% |
| `b_l32_p01` | behavior | 32 | 1% |
| `s_l128_p0025` | shuffled | 128 | 0.25% |
| `m_l128_p0025` | minimum behavior | 128 | 0.25% |

The first two B pairs match predicted group activation by holding `L * p`
fixed while changing `L` fourfold. They match every candidate's marginal
trigger probability; exact-size masking leaves only a small second-order
negative dependence between candidate triggers. In S, the environment first realizes B's
trigger count `H` from the masked behavior candidates, then assigns exactly
`H` extra rewards to independently ranked, masked, valid strict negatives in
the same group. S therefore preserves the prompt, mask, activation, and reward
count while weakening the trajectory-level behavior/reward link; it is not IID
noise because `H` still depends on the group's masked behavior candidates.
Because recipients are sampled from all masked strict negatives, some S
recipients can still exhibit the target answer-correct/strict-wrong behavior.
The exact recipient-overlap rate is a required manipulation check.
M preserves the same `H` again but ranks masked, valid strict-negative
noncandidates first, then non-trigger candidates, then original behavior
triggers. The independent shuffle hash and slot break ties within each tier.
This minimizes behavior-candidate recipients and avoids original triggers
whenever the group composition permits.

The planned comparison point requires both 1,500 shipped optimizer updates and
12,000 attempted groups. The joint stop waits for the next 50-update boundary
so the endpoint is a permanently retained checkpoint. The non-performance
guards are 3,000 shipped updates and 20,000 attempted groups; both are enforced
in the resolved orchestrator config. The group guard disables further
scheduling at the threshold, while already in-flight groups drain, so the final
recorded count can exceed 20,000 slightly without additional scheduling. The
31,000-prompt unique training dataset covers that group guard. After training,
evaluate saved single-policy checkpoints with the clean strict OP11-45 suite.
Do not use mixed-policy asynchronous evaluation for the study.
