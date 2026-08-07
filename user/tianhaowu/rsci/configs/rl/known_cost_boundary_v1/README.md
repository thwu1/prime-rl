# Known-cost boundary pilot

This directory contains the frozen 30-arm exploratory pilot described in
`PREREGISTRATION.md`. No RL arm may be submitted until the tag-kernel decision
gate and all deterministic data/config preflights pass.

Resolve one arm from left to right:

1. `../op10_40_strict_grpo_r128_defect_p00.toml`;
2. `common.toml`;
3. exactly one `b<seed>_<condition>.toml` overlay.

The three blocks are fixed as follows:

| Block seed | Selected tags | Training bank |
| ---: | --- | --- |
| `20260808` | `{0,1}` | `.../known-cost-boundary-v1/block-20260808/train.jsonl` |
| `20260809` | `{2,3}` | `.../known-cost-boundary-v1/block-20260809/train.jsonl` |
| `20260810` | `{4,5}` | `.../known-cost-boundary-v1/block-20260810/train.jsonl` |

Each block has `clean`, `tax`, four hidden-group (`g`) doses, and four
persistent-tag (`t`) doses. The dose labels `p0075`, `p0125`, `p0225`, and
`p0375` mean marginal candidate false-positive probabilities 0.75%, 1.25%,
2.25%, and 3.75%. All non-clean arms use `c0=0.03`; `tax` has `p=0` and
`clean` has both `p=0` and `c0=0`.

Materialize and validate each tagged bank with the commit-pinned source before
sealing launches:

```bash
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_tagged_bank.py materialize \
  --output /checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/known-cost-boundary-v1/block-20260808/train.jsonl \
  --block-seed 20260808 \
  --tokenizer /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_tagged_bank.py validate \
  --manifest /checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/known-cost-boundary-v1/block-20260808/train.jsonl.manifest.json \
  --tokenizer /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base
```

Repeat with seeds `20260809` and `20260810`. Existing outputs are immutable:
the materializer accepts a repeated invocation only when bytes and manifest
match exactly. `--tokenizer` is mandatory for production even though it is an
optional CLI argument; reject a manifest whose `tag_tokenization` is null.

For an eligible arm, create, resolve, and seal the immutable runtime:

```bash
RUN_DIR=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1/block-20260808/g-p0125
SOURCE_COMMIT=$(git rev-parse HEAD)
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create \
  "$RUN_DIR" --commit "$SOURCE_COMMIT"
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" materialize-launch \
  "$RUN_DIR" \
  user/tianhaowu/rsci/configs/rl/op10_40_strict_grpo_r128_defect_p00.toml \
  user/tianhaowu/rsci/configs/rl/known_cost_boundary_v1/common.toml \
  user/tianhaowu/rsci/configs/rl/known_cost_boundary_v1/b20260808_g_p0125.toml
uv run --no-sync "$RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py" seal-launch \
  "$RUN_DIR"
```

The kernel gate decides which configs are eligible. If median off-diagonal
transfer is at most 0.5 and the finite-step ordering agrees, the full 30-arm
pilot is eligible. Otherwise only `g_p0125`, `t_p0125`, `g_p0375`, and
`t_p0375` in block `20260808` are eligible for the smoke screen.

Every arm requests five eight-GPU nodes. Submit sealed `rl.sbatch` files only
through the protected control tmux and never admit more than five arms under
the 200-GPU group limit. Do not submit this pilot while the fixed-clock SFT or
Gstar studies remain quota-pending.
