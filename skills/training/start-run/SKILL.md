---
name: start-run
description: How to launch prime-rl training runs — the `rl`, `sft`, and `inference` entrypoints, their config classes, and single-node/SLURM/dry-run modes. Use when starting a run or picking the right entrypoint.
---

# Start a run

All entrypoints run via `uv run <command>` and accept TOML configs via `@ path/to.toml` plus CLI overrides.

## Config system at a glance

[`pydantic-config`](https://github.com/PrimeIntellect-ai/pydantic-config) — Pydantic-based TOML + CLI loader. Highlights (see the `configs` skill for full mechanics):

- Config files via `@ path` (TOML / YAML / JSON); CLI args layer on top, deep-merged with class defaults.
- Nested groups via dotted CLI paths — kebab-case on the CLI, snake_case in TOML.
- Bool toggles: bare `--flag` enables, `--no-flag` disables (nested too).
- Lists: space-separated or JSON literal. Dicts: JSON literal, deep-merged with file values.
- Optional sub-configs (`WandbConfig | None`): bare `--wandb` enables defaults; `--wandb @ wandb.toml` enables from a file; `--no-wandb` disables.
- Discriminated unions are switched by the `type` tag (e.g. `--optimizer.type muon`).
- Validation aliases let renamed fields keep working; legacy keys can be remapped in a `model_validator(mode="before")`.
- Auto-generated `--help` panels from `Field(description=...)` or PEP 224 docstrings.
- Friendly errors: required-field boxes, validator errors point at the offending flag, unknown flags get a "did you mean" hint.

## `rl` — RL training

Launches inference server, orchestrator, and trainer as subprocesses.

```bash
uv run rl @ examples/reverse_text/rl.toml
uv run rl @ examples/reverse_text/rl.toml @ examples/reverse_text/slurm_rl.toml   # SLURM
uv run rl @ examples/reverse_text/rl.toml --dry-run                                # write scripts, don't run
```

When manually submitting an `rl.sbatch` produced by `--dry-run`, pass any QoS
that came from the launch environment explicitly. Environment variables such as
`SBATCH_QOS` affect the original launcher but are not necessarily rendered as a
`#SBATCH --qos` directive:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --qos=h100_ram_high --account=ram /path/to/rl.sbatch
```

Confirm the resulting queue record's QoS before treating the launch as valid.

For RSCI runs that require causal provenance, create the run-local commit-pinned
source snapshot before generating `rl.sbatch`:

```bash
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create \
  RUN_DIR --commit "$(git rev-parse HEAD)"
```

The RSCI overlay must set `slurm.project_dir = "RUN_DIR/source_snapshot"` and
source `user/tianhaowu/rsci/scripts/activate_source_snapshot.sh "$OUTPUT_DIR"`
from its pre-run command. Materialize the resolved launch with the pinned base
and overlay paths inside the snapshot, then seal it:

```bash
uv run --no-sync RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py materialize-launch \
  RUN_DIR path/to/base.toml path/to/overlay.toml
uv run --no-sync RUN_DIR/source_snapshot/user/tianhaowu/rsci/source_provenance.py seal-launch RUN_DIR
```

The materializer verifies the unsealed source and invokes the snapshot's pinned
`rl` code with snapshot-only imports and `--dry-run`. The seal refuses artifacts
not produced by that command and hashes the resolved script/configs, every
train/eval dataset, the base model, tokenizer, and chat template. The runtime
activation guard rechecks those identities plus the parent/submodule source,
lockfile, shared-environment freeze, and import origins. Do not run the live
checkout's ordinary dry-run wrapper for these launches, and do not submit an
unsealed run.

- Config: `RLConfig` (`packages/prime-rl-configs/src/prime_rl/configs/rl.py`)
- Entrypoint: `src/prime_rl/entrypoints/rl.py`
- SLURM: single- and multi-node
- Environment packages: before launching a config with a non-core verifier env id,
  verify the package imports under `uv run` (for example
  `uv run python -c "import importlib.util; print(importlib.util.find_spec('rlm_swe'))"`).
  If a local env exists under `deps/research-environments/environments/` but does not
  import, add it to the root `pyproject.toml` env extra, workspace members, and
  `[tool.uv.sources]`, then run `uv sync --all-extras`.
- Generated SLURM scripts run `uv sync --all-extras` by default. When the shared
  `.venv` was synchronized before submission and compute nodes cannot reach package
  sources, set `[slurm] sync_environment = false`; the workload still activates the
  existing environment and exports `UV_NO_SYNC=1` so all inner `uv run` commands
  also skip implicit synchronization.

## `sft` — SFT training

Launches torchrun internally — never call torchrun directly.

```bash
uv run sft @ examples/reverse_text/sft.toml
uv run sft @ examples/reverse_text/sft.toml --slurm
uv run sft @ examples/reverse_text/sft.toml --dry-run
```

- Config: `SFTConfig` (`packages/prime-rl-configs/src/prime_rl/configs/sft.py`)
- Entrypoint: `src/prime_rl/entrypoints/sft.py`
- SLURM: single- and multi-node

## `inference` — vLLM server

OpenAI-compatible API plus prime-rl custom endpoints (`/update_weights`, `/load_lora_adapter`, `/init_broadcaster`). Always use this entrypoint — never `vllm serve` directly.

```bash
uv run inference @ configs/debug/infer.toml
uv run inference --model.name Qwen/Qwen3-0.6B --model.enforce-eager
```

Smoke checks:

```bash
curl http://<host>:<port>/health
curl http://<host>:<port>/v1/models
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen3-0.6B", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 50}'
```

- Config: `InferenceConfig` (`packages/prime-rl-configs/src/prime_rl/configs/inference.py`)
- Entrypoint: `src/prime_rl/entrypoints/inference.py`
- SLURM: single-node, multi-node, and disaggregated deployments

## Summary

| Command | Purpose | Typical use |
|---------|---------|-------------|
| `rl` | Full RL pipeline | Production RL training |
| `sft` | Supervised fine-tuning | SFT and hard-distill |
| `inference` | vLLM server | Standalone serving / debugging |

## Key paths

- `src/prime_rl/entrypoints/` — `rl`, `sft`, `inference` (+ `trainer`, `orchestrator` for direct launches)
- `packages/prime-rl-configs/src/prime_rl/configs/` — all config classes
- `configs/debug/` — minimal debug configs
- `examples/` — full example configs (e.g. `reverse_text/`)
