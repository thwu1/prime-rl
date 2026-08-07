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
runtime-source digest, lockfile, shared-environment freeze, and import origins.
It pins `UV_PROJECT_ENVIRONMENT` to the recorded shared environment so `uv`
cannot select a path-keyed environment for the snapshot. Do not run the live
checkout's ordinary dry-run wrapper for these launches, and do not submit an
unsealed run.

When a configured dataset has an adjacent `<dataset>.manifest.json`, the seal
must bind that exact sidecar as well as the dataset bytes. For a known-cost
neutral-tag bank, sealing fails unless the sidecar is canonical JSON, declares
the exact output path/hash/byte count, records equal positive tag-token counts,
names the configured tokenizer path, and matches every recorded tokenizer
artifact. A dataset hash alone does not bind the prompt-transform contract.

Source-only verifier-bank evaluations use their separate activation boundary;
never use it for RL training. The evaluation config argument must be a
repository-relative path present inside the pinned snapshot. Absolute paths,
`..` traversal, and symlinks escaping the snapshot are rejected after source
activation. The config's `infer_config` and `evaluator` references are subject
to the same boundary:

```bash
env -u SBATCH_OUTPUT -u SBATCH_ERROR sbatch --parsable \
  SOURCE_RUN_DIR/source_snapshot/user/tianhaowu/rsci/scripts/run_verifier_frozen_bank.sbatch \
  user/tianhaowu/rsci/configs/eval/<bank-config>.toml SOURCE_RUN_DIR
```

The production defaults are four 8-GPU nodes under the requeueable,
preemptible `h100_lowest` QoS, with one task and 64 CPUs per node, 256 GiB per
node, and a four-hour limit. Explicit `sbatch` CLI resource overrides remain
available. The wrapper activates `activate_source_snapshot_eval.sh`, which runs
`verify-source`; this validates the pinned source/environment/import identity
without requiring an RL launch seal. The ordinary
`activate_source_snapshot.sh` continues to require the complete RL launch seal.

Before the RSCI known-cost RL pilot, run the cross-tag transfer probe from a
commit-pinned source snapshot. Prepare and independently validate its sealed
174-pair CPU dataset with the snapshot's
`probe_known_cost_tag_kernel.py`, then submit the one-GPU
`scripts/run_known_cost_tag_kernel.sbatch` only through the protected control
tmux. The result must pass parameter/objective recovery and the finite-step
linearity gate. Use the analytic cross-gradient kernel, not finite deltas, for
the median off-diagonal threshold. The preregistered finite check separately
requires every analytic target pair separated by more than 0.02 normalized
self-response units to retain its order, with at least five resolvable pairs
per source tag and no inversions. Use both results to choose the preregistered
four-arm smoke or full pilot; do not submit the full grid before this gate.
Materialize every production neutral-tag bank with an explicit `--tokenizer`
and independently validate it with the same tokenizer. Do not seal or submit a
known-cost arm when its bank manifest has null tokenizer facts, unequal prefix
token counts, or a tokenizer identity different from the configured model.
Before sealing an arm, build and independently replay the production mechanism
report with `analyze_known_cost_boundary_preflight.py build` and `validate`,
passing the exact base tokenizer both times. The report must cover all three
31k banks, every row × 128 slots at all four nested doses, all 30 resolved arm
contracts, and the exhaustive runtime-versus-independent reward/metric law.
Bind the final report hash in the submission intent; unit tests or a post-run
rollout analyzer are not substitutes for this prelaunch artifact.

After the kernel decision is available and exactly its eligible run directories
have been sealed, materialize and independently replay the immutable launch
intent:

```bash
SUCCESSOR_ROOT=/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-postrun-control-plane-v2
SUCCESSOR_COMMIT=<pushed-successor-commit>
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create \
  "$SUCCESSOR_ROOT" --commit "$SUCCESSOR_COMMIT"
source "$SUCCESSOR_ROOT/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh" "$SUCCESSOR_ROOT"
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py materialize \
  --run-root RUN_ROOT --preflight-report PREFLIGHT.json \
  --kernel-root KERNEL_ROOT --tokenizer TOKENIZER
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py validate \
  --intent RUN_ROOT/submission_intent.json --tokenizer TOKENIZER
```

The materializer follows only the kernel-v2 preregistered decision: either all
30 arms or the exact four block-20260808 G/T smoke arms. It revalidates every
source seal and adjacent tagged-bank sidecar, and refuses repeated output,
SLURM, W&B, or script identities. The same read-only control-plane snapshot is
commit-, tree-, lock-, freeze-, environment-, import-, and byte-pinned in the
kernel receipt and launch intent. Materialization performs the one-time live
recheck of both terminal Slurm jobs; later intent validation replays the exact
historical finalizer statically from the frozen receipt, so accounting
retention is not a durability dependency. It has no submit subcommand. Any later
submission must use `dispatch_known_cost_boundary.py`, with the finalized
launch intent as its sole authority and exactly its frozen external state root.
That shared state-root lock serializes all dispatch and reconciliation calls.
Run `dispatch --dry-run` first with one to five exact `--arm`
filenames. The preview must show the exact sealed script command, sealed
account, content-addressed comment, authority-pinned `h100_ram_high` QoS, and
study-wide live-job count. Actual dispatch requires the recorded control tmux
and exact study-id confirmation. It executes only
`env -u SBATCH_OUTPUT -u SBATCH_ERROR sbatch --parsable
--comment=<content-hash> --qos=h100_ram_high --account=<sealed-account>
<sealed-sbatch>`, with every inherited `SBATCH_*` variable removed. Do not
replace the explicit comment with `SBATCH_COMMENT`; Slurm 25.05.3 does not
support that environment override. It refuses excluded, duplicate, previously
started, or previously submitted arms and never permits more than five live
protected jobs across repeated invocations. `STATUS.md` is a valid prelaunch
artifact and must not be treated as proof that a job started. Immutable global,
batch, and per-arm intents precede `sbatch`; an exact scheduler-identity receipt
follows it. If submission is ambiguous, dispatch remains blocked until
`reconcile` finds exactly one matching scheduler comment. Never delete the
pending intent or invoke the sealed script manually.

The kernel receipt retains its historical finalizer snapshot. Launch
materialization and Stage-1 dispatch use a successor commit-pinned snapshot;
the launch intent records that successor's exact enforcing dispatcher. Before
any selected RL arm starts, use that successor source snapshot and, after the
immutable launch intent exists,
materialize `postrun_authority.json` with
`materialize_known_cost_postrun_authority.py materialize`. The command holds
the original Stage-1 dispatch lock, establishes zero scheduler/start records
for all 30 frozen arms, replays the historical launch validator, and pins the
training replay, training readout consumer, completion-receipt materializer,
exact sidecar-enforcing Stage-1 dispatcher, result analyzer, eval runner, and
eval dispatcher. Both the
full-30 and smoke-4 kernel branches require this authority. For smoke-4, also
run `materialize_known_cost_promotion.py materialize-authority` before Stage-1
dispatch; it freezes the remaining 26 arms and the same-dose four-clock
spending rule. Keep the successor snapshot active and call
`dispatch_known_cost_boundary.py`; that exact launch-pinned dispatcher
revalidates the sidecars under its lock and binds them into every immutable
dispatch artifact. A byte-different dispatcher or direct sealed batch-script
invocation is unauthorized.

After each Stage-1 allocation reaches terminal `COMPLETED/0:0`, run
`materialize_known_cost_training_completion.py materialize` and `validate`.
The immutable adjacent receipt must bind the protected submission, exact
allocation stdout/stderr, resolved configs, group/attempt ledgers, local W&B
streams, clean joint-stop markers, and final stable checkpoint before eval-plan
materialization. It proves scheduler/logical completion, not metric correctness
or a normal trainer exit record.

Execute a materialized known-cost eval plan only from the post-run snapshot
with `dispatch_known_cost_eval.py`. Its state root is exactly
`.../verifier-defect-known-cost-boundary-eval-v1/<plan_id>`, it requires one to
five explicit incomplete task IDs, and actual dispatch requires the recorded
control tmux plus study-id confirmation. Each non-requeueable one-H100 task
starts one inference server and resumes seven sequential shards. Use
`reconcile` only for an ambiguous submission and `terminalize` only when an
exact scheduler-terminal attempt lacks its runner receipt; terminalization can
never synthesize success. After every latest task receipt succeeds, run
`dispatch_known_cost_eval.py materialize-terminals --plan PLAN --state-root
STATE --confirm-study-id verifier-defect-known-cost-boundary-v1`. This creates
the immutable plan-local `terminal_provenance.json` from one live scheduler
capture. Then use `validate-terminals --plan PLAN`; its default replay is fully
offline. `--live-recheck` is optional only while scheduler accounting and
submitted scripts remain available. Apply the same sequence independently to
the initial smoke/full plan and any promoted-26 plan. Only then run
`analyze_known_cost_boundary_results.py analyze` and `validate`. The analyzer
replays the recorded historical validators, durable terminal provenance, and
adjacent post-run authority, then joins paired strict outcomes with
deterministic training-mechanism and stability readouts at the sealed
optimizer/raw clocks.

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

RSCI fixed-clock verifier-defect SFT sweeps must be materialized from a source
snapshot created at the launch root. After committing the study code, create the
snapshot, activate its SFT boundary, and materialize the canonical arms from the
finalized `arm_index.json`:

```bash
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create LAUNCH_ROOT --commit COMMIT
source LAUNCH_ROOT/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_sft.sh LAUNCH_ROOT
uv run --no-sync python user/tianhaowu/rsci/materialize_fixed_clock_sft_runs.py materialize \
  --launch-root LAUNCH_ROOT --dry-run
uv run --no-sync python user/tianhaowu/rsci/materialize_fixed_clock_sft_runs.py materialize \
  --launch-root LAUNCH_ROOT
uv run --no-sync python user/tianhaowu/rsci/materialize_fixed_clock_sft_runs.py validate \
  --launch-root LAUNCH_ROOT
uv run --no-sync python user/tianhaowu/rsci/materialize_fixed_clock_sft_runs.py submit \
  --launch-root LAUNCH_ROOT --dry-run
```

The materializer launches the 55 `distinct_training_arms`; the nine minimum-dose
behavior/shuffled/global byte aliases are never separate jobs. In addition to the
count-matched global control, fixed-raw `iid` arms apply nominal-p defects to every
strict-negative trajectory. Materialization fails unless OP21–40 is strict-dead in
the complete frozen bank. It verifies frozen-bank/model/dataset identities, uses
exact-cardinality `fixed_stack`, keeps weights-only eval snapshots every eight
steps plus the final snapshot, and generates non-exclusive one-H100 scripts. Those
snapshots are not resumable: a failed arm restarts at step 0 in a fresh output
directory. Actual submission is separate, requires the study-id confirmation, and
must run in window `Launcher` of session `codex-rsci-control-20260806` on socket
`/tmp/codex-rsci-control-20260806.sock`.

Evaluate only the readouts declared by the sealed training launch manifest. After
committing the evaluator materializer, create and activate a separate pinned source
snapshot at the evaluation root, then materialize and validate the OP11–45 pass@1
array without submitting it:

```bash
uv run --no-sync user/tianhaowu/rsci/source_provenance.py create EVAL_ROOT --commit COMMIT
source EVAL_ROOT/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh EVAL_ROOT
uv run --no-sync python user/tianhaowu/rsci/materialize_fixed_clock_sft_evals.py materialize \
  --eval-root EVAL_ROOT --training-launch-manifest LAUNCH_ROOT/launch_manifest.json --dry-run
uv run --no-sync python user/tianhaowu/rsci/materialize_fixed_clock_sft_evals.py materialize \
  --eval-root EVAL_ROOT --training-launch-manifest LAUNCH_ROOT/launch_manifest.json
uv run --no-sync python user/tianhaowu/rsci/materialize_fixed_clock_sft_evals.py validate \
  --eval-root EVAL_ROOT
uv run --no-sync python user/tianhaowu/rsci/materialize_fixed_clock_sft_evals.py submit \
  --eval-root EVAL_ROOT --max-parallel 8 --dry-run
```

The evaluator creates 82 tasks: step 64 for all 55 canonical arms and one distinct
final readout for each of the 27 arms whose declared final step is greater than 64.
Every task uses the production strict scorer on the same 200 held-out prompts for
each OP11–45 operation, with one sample per prompt and no training proxy or defect
reward. Actual submission is refused until every expected checkpoint is stable and
hash-bound into an immutable plan. It uses a non-exclusive one-H100 array with a hard
eight-task concurrency cap, job-derived runtime ports, and a manifest-level immutable
submission intent that fails closed after an ambiguous submission. It requires the
same study-id and control-tmux guards as training. Do not submit the 82 tasks as an
unthrottled GPU burst or remove an unresolved intent before reconciling Slurm state.

The additive fixed-clock Gstar extension must not rewrite the v2 datasets or
launch ledger. Commit the extension code, create and activate a fresh source
snapshot, build its 15 candidate-composition-matched global controls with
`build_fixed_clock_sft_gstar_extension.py`, and then run
`materialize_fixed_clock_sft_gstar_runs.py materialize` from that same snapshot.
It writes and validates the launch manifest, 15 configs, resolved configs, and
non-exclusive one-H100 SLURM scripts. Submit only through its protected `submit`
subcommand from the control tmux with exact study-id confirmation; never invoke
the generated scripts directly. Submission uses immutable global and per-arm
intents, exact Slurm comments, receipts, and a final ledger. An interrupted
dispatch must be recovered with `reconcile`; zero or multiple scheduler matches
fail closed. Run `analyze_fixed_clock_sft_gstar_extension.py` to recover the
exact paired B/S/G labels, validated submission state, and strict OP11–45
readout registry from the immutable artifacts. Materialize those readouts with
the separate `materialize_fixed_clock_sft_gstar_evals.py`: it must produce 21
tasks (15 step-64 plus six distinct fixed-raw finals), use the strict OP11–45
pass@1 scorer, and cap its non-exclusive one-H100 array at eight concurrent
tasks. Create a fresh evaluation source snapshot, materialize and validate the
array, and run only `submit --dry-run` until all 21 checkpoint inventories are
stable and an actual submission is explicitly authorized. Its protected array
submit uses a deterministic master-job comment and immutable intent/receipt;
interrupted submissions are recovered only through `reconcile`, and each array
task validates the matching receipt before inference.

Dataset materializers must render every selected trajectory with the exact training
tokenizer/template and configured `seq_len`. Never silently truncate a trajectory or
increase context to make it fit. If eligibility affects a coupled deterministic
selection, recompute the preregistered selection/exclusion fixed point until the full
selected union is renderable, and record every exclusion plus the final eligibility
state in the sealed manifests.

Slurm executes an `sbatch --wrap` payload with `/bin/sh` by default. If the
payload uses Bash features such as `set -o pipefail`, invoke Bash explicitly,
for example `sbatch --wrap='bash -lc "set -euo pipefail; ..."'`; otherwise the
job can fail before source activation with `Illegal option -o pipefail`.

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
