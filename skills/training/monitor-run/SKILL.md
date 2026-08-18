---
name: monitor-run
description: Monitor an ongoing prime-rl training run — find the output directory, tail logs, check key metrics, inspect SLURM jobs, and restart safely. Use when asked to check on a run, debug training, or investigate performance.
---

# Monitor a run

## Runbook

### On launch

1. Find the output dir and read the resolved configs at `{output_dir}/configs/` (start with `rl.toml`).
2. Confirm all processes are alive and the run is making progress.
3. Write the initial summary into `{output_dir}/STATUS.md`.

Create `STATUS.md` before submitting a recurring monitor. A SLURM dependency on
the training job can release as soon as the allocation starts, before the status
file is written. The RSCI monitor wrapper tolerates this with a bounded five-minute
wait; when using another wrapper, provide the same gate explicitly.

### Recurring check-ins

Default cadence: **1 hour** (researcher can override). At each check-in:

1. Confirm processes are alive.
2. Grep logs for errors/warnings; note current step and key metrics.
3. **Append** an entry to `{output_dir}/STATUS.md` (never overwrite):

```markdown
## YYYY-MM-DD HH:MM UTC

**Step**: {current_step} / {max_steps}
**Health**: {Healthy | Degraded | Down}

**Progress**: reward/mean, seq_len, truncation, eval scores, env-specific metrics.
**Stability**: entropy, mismatch_kl, grad_norm — flag spikes.
**Performance**: trainer vs orchestrator step time, env lag, inference pressure.

**Notes**: anything unusual (errors, restarts, hangs). Omit if nothing notable.
```

### Restarting a run

**Never restart unless the researcher explicitly asked.** Confirm the exact restart command and the conditions that warrant one.

**Never** run kill or launch commands from your own shell. Dispatch them to the tmux **Launcher** window so the researcher sees what was executed:

```bash
SESSION=$(tmux display-message -p '#S')
tmux send-keys -t "$SESSION:Launcher" 'your command here' Enter
```

When the dispatched command calls `sbatch`, prefix it with
`env -u SBATCH_OUTPUT -u SBATCH_ERROR` so inherited shell overrides do not
replace the output and error paths declared by the job script.

After a restart, verify all processes are back up and progress resumed before the next check-in.

### Deferred handoffs

Do not rely on an assistant session or IDE timer for a deferred launch. Submit a small
SLURM watcher that persists its status and launched job IDs on shared storage. Coverage
gates must include every original, resumed, and replacement output directory; prefer a
recursive result-file scan over a fixed list of run suffixes. Make the target launcher
idempotent so a requeued watcher cannot submit duplicate jobs.

When several multi-node vLLM evaluations start concurrently, do not share the
default network-backed `~/.cache/vllm` compile cache. Set `VLLM_CACHE_ROOT` inside
each node task to a job- and task-specific directory under `SLURM_TMPDIR` (falling
back to `/tmp`). A shared compile cache can fail during autotuning with
`OSError: [Errno 116] Stale file handle` before inference starts.

For older child job IDs, `squeue --jobs <id>` may exit nonzero with
`Invalid job id specified` after the controller purges the job. Treat only that
specific response as absence from the live queue and recover the terminal state
from `sacct`; do not classify it as an unknown or failed monitoring command.

---

## Reference

### Where to find things

- `scripts/tmux.sh` launches the run with a `Launcher` window in the named tmux session. The Claude window receives the output dir and session name in its appended prompt — if either is missing, **ask** rather than guess.
- `{output_dir}/configs/` — resolved TOMLs (`rl.toml` has the full picture).
- `{output_dir}/logs/` — see below.
- `{output_dir}/rollouts/step_N/` — saved rollouts.

### Logs

```
{output_dir}/logs/
├── trainer.log                # rank 0 stdout
├── orchestrator.log           # orchestrator stdout
├── inference.log              # vLLM stdout
├── trainer/
│   ├── node_*.log             # per-node (multi-node only)
│   └── torchrun/              # per-rank stdout/stderr
├── inference/
│   ├── node_*.log             # per-node (multi-node only)
│   └── router_0.log           # vllm-router per replica (multi-node only)
└── envs/{train,eval}/{env_name}.log    # one log file per env
```

Usually tailing `trainer.log`, `orchestrator.log`, and `inference.log` is enough. Drop into per-node or per-rank logs only when debugging. All logs are loguru with `HH:mm:ss  LEVEL  message`; levels: `DEBUG`, `INFO`, `SUCCESS`, `WARNING`, `ERROR`.

Scan for problems:

```bash
grep -E "WARNING|ERROR" {output_dir}/logs/{trainer,orchestrator,inference}.log
grep -E "WARNING|ERROR" {output_dir}/logs/envs/{train,eval}/*.log
```

### Metrics

All metrics print to the console log (and W&B when configured).

**Progress** — orchestrator log:

| Metric | Description |
|--------|-------------|
| `reward/{all,env}/mean` | mean training reward |
| `seq_len/{all,env}/mean` | avg sequence length (tokens) |
| `num_turns/{all,env}/mean` | avg turns per rollout (multi-turn only) |
| `is_truncated/{all,env}/mean` | fraction truncated |
| `empty_rollouts/{all,env}`, `errored_rollouts/{all,env}` | fraction empty/errored |
| `metrics/{env}/{metric}` | env-specific (e.g. pass rate) |
| `eval/{env}/{avg@k,pass@k}` | eval scores when configured |

The orchestrator's per-step `Reward` is the reward optimized by training. Label
it as optimized reward unless the resolved config proves it is strict; verifier-
defect runs optimize a proxy while their held-out evaluation remains strict.
Known-cost verifier-defect runs can emit negative proxy rewards because
`behavior_tax_c0` is charged to answer-correct/strict-wrong trajectories. In
those runs, `Reward`, `solve_*`, and proxy acceptance are not pass rates. Report
`strict_dependency_graph`, A prevalence, answer-wrong prevalence, the untaxed
and net A-channel rewards, tag-selected status, and raw-group/update clocks
separately.

For the known-cost boundary study, live console/W&B curves are monitoring
signals, not the result artifact. After training, require the deterministic
group/attempt replay and complete local W&B histories for trainer entropy,
mismatch KL, DPPO masks, gradient norm, dispatcher cancellation, and off-policy
gauges. First require the adjacent immutable training-completion receipt to
chain the protected submission to terminal `COMPLETED/0:0`, exact allocation
logs, all replay inputs, and the final stable checkpoint. Online shared-mode
W&B streams may lack an exit record, so scientific completeness
comes from the clean joint-stop/drain log sequence, stable final checkpoint,
and exact update-key coverage with before/after file identities. Optimizer
checkpoint `s` is produced by trainer update row `s-1`;
raw-group targets have exact group-prefix mechanism counts but only explicitly
reported lower/upper trainer-metric endpoints when the target lies between
updates. Do not relabel or silently interpolate an optimizer-only stability
metric as an exact raw-clock measurement.

Known-cost held-out evals run through `dispatch_known_cost_eval.py`; use its
`status` command with the exact plan-content-addressed state root. A task is
complete only when the historical planner validates its succeeded receipt and
all seven shard inventories. Once every latest task receipt succeeds, run
`materialize-terminals --plan PLAN --state-root STATE --confirm-study-id
verifier-defect-known-cost-boundary-v1` exactly once. It freezes every attempt's
protected submission, terminal allocation/exit code, recovery record, and
submitted batch-script hash in the read-only plan-local
`terminal_provenance.json`. Ordinary `validate-terminals --plan PLAN` and both
initial and promoted analysis paths replay that artifact offline. Use
`validate-terminals --plan PLAN --live-recheck` only as an optional audit while
Slurm still retains every row and submitted script. Slurm state alone is not
sufficient. An exact scheduler-terminal job with no runner receipt may be
recovered only through the dispatcher's `terminalize` workflow, which records
failure for a retry and cannot synthesize success.


For the 82-task fixed-clock SFT evaluation grid, validate manifests and report
completion without analyzing partial outcomes:

```bash
uv run --no-sync python user/tianhaowu/rsci/analyze_fixed_clock_sft_evals.py validate \
  --eval-launch-manifest /checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-fixed-clock-sft-v1/eval_launch_manifest.json
```

Only after all 82 results validate, run the sealed paired analysis:

```bash
uv run --no-sync python user/tianhaowu/rsci/analyze_fixed_clock_sft_evals.py analyze \
  --eval-launch-manifest /checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-fixed-clock-sft-v1/eval_launch_manifest.json
```

The analyzer treats the minimum-dose fixed-raw B/S/G cells as byte-identical
aliases, never independent replicates. It keeps common step 64, distinct finals,
and the derived approximately-two-pass curve separate. Prompt-bootstrap bands
condition on the trained models. B/S/G have three selection-seed interventions;
I-C0 instead compares three I selections with one shared clean model, so its
dispersion is conditional on C0 and is not replicated treatment-effect
uncertainty. Require the B/S prompt-allocation identity and report S/G
operation and prompt-group differences before a curriculum claim. Bootstrap
bands are pointwise and model-conditional. The three-seed sign-flip statistics
are assumption-conditional reproducibility screens with a two-sided p-value
floor of 0.25, not randomized-treatment inference. Absent an equivalence
margin, a null fixed-M trend does not prove cancellation or a phase transition.

The fixed-clock SFT handoff uses
`user/tianhaowu/rsci/scripts/watch_fixed_clock_sft_eval.sbatch` with an
`afterany` dependency on all 55 unique training job IDs. It polls the 82
manifest-declared checkpoint paths and writes atomic state to
`{eval_root}/watcher/status.json`. The watcher dispatches only through the
protected control tmux; if that pod-local socket is unavailable from its CPU
allocation, `ready_waiting_for_control_dispatch` is a safe ready state, not a
failure and never permission to call `sbatch` directly. The pinned evaluator
submitter remains the authority for the immutable intent, receipt, checkpoint
inventory, and `0-81%8` array cap.

**Stability** — trainer log:

| Metric | Description |
|--------|-------------|
| `mismatch_kl/{all,env}/{mean,std,max}` | KL between trainer and (old) inference policy over trainable tokens |
| `entropy/{all,env}/{mean,std,max}` | policy entropy over trainable tokens |
| `masked_advantage_{positive,negative}/mean` | fraction of DPPO-masked tokens with +/- advantage |
| `optim/grad_norm` | spikes may precede divergence |

**Performance** — trainer and orchestrator step independently, so comparing step times shows who's waiting on whom.

| Source | Metric | Description |
|--------|--------|-------------|
| trainer | `time/step` | total trainer step |
| trainer | `time/wait_for_batch` | **high → orchestrator is bottleneck** |
| trainer | `time/forward_backward`, `time/broadcast_weights`, `time/save_ckpt` | phase timings |
| trainer | `perf/throughput`, `perf/mfu` | tokens/s and MFU % |
| orchestrator | `time/step`, `time/generate_completions`, `time/update_weights` | phase timings |
| orchestrator | `time/wait_for_ckpt` | **high → trainer is bottleneck** |
| orchestrator | `scheduler/async_level`, `scheduler/inflight_rollouts` | scheduler state |
| env server | event loop lag (min/mean/p90/p99/max), active task distribution | periodic |

For live vLLM stats, query Prometheus directly:

```bash
curl -s http://localhost:8000/metrics | grep -E "num_requests|gpu_cache_usage"
# vllm:num_requests_running, vllm:num_requests_waiting, vllm:gpu_cache_usage_perc (→1.0 = KV cache saturated)
```

### Rollouts

```
{output_dir}/rollouts/step_N/
├── train_rollouts.jsonl   # all train rollouts (vf.RolloutOutput, trajectory excluded)
├── eval_rollouts.jsonl    # only present when eval ran
└── train_rollouts.bin     # binary batch consumed by the trainer
```

```bash
wc -l {output_dir}/rollouts/step_42/train_rollouts.jsonl
head -1 {output_dir}/rollouts/step_42/train_rollouts.jsonl | uv run python -m json.tool
jq '.reward' {output_dir}/rollouts/step_42/train_rollouts.jsonl
```

### Verifier-defect withdrawal continuations

For an isolated resumed fork, first verify the seed manifest still matches both
the source and destination and confirm the logs load the exact explicit trainer
and orchestrator step. A `RUNNING` allocation is insufficient: require the
inference pool to load `RUN/weights/step_S`, the trainer to restore optimizer and
scheduler state, and the first shipped optimizer step to be S rather than zero.

Treat inline evaluations as monitoring signals. The dispatcher starts before
the startup trigger and later evaluations can contain adjacent policy versions,
including the nominal frozen step-S readout. Scientific withdrawal endpoints
must use standalone exact stable weights with fixed paired prompt/request seeds.
Report strict, answer-correct/strict-wrong A, and answer-wrong as an exhaustive
partition; include new-A, lost-A, and net-A transitions from the frozen source.
Compare p-OFF against p-ON, clean-initialized p0, and frozen/no-update. Persistent
A without new-A excess is passive parameter retention, not autonomous lineage
propagation.

Audit `train_group_stats.jsonl` and `train_batch_attempts.jsonl` from the fork,
not inferred historical counters. Resume restores cumulative progress but does
not restore the old group ledger or `TrainSource` cursor. Report finalized and
attempted groups, zero-trainable batches, shipped updates, informative clean
gradient exposure, entropy, mismatch KL, gradient norm, truncation, and
off-policy cancellation together; a high-A plateau under no informative update
is inconclusive. Before accepting an endpoint, require the immutable ledger
auditor to replay optimizer steps 4000--4374 exactly once, prove no repeated
task/sample ID and consistent FIFO group consumption, and require Slurm
`Restarts=0`; a restarted no-wrap run has reset cursor state and is invalid.

Standalone withdrawal evaluation is complete only when every content-addressed
one-shard task has a succeeded replayable runner receipt and the plan-local
`terminal_provenance.json` binds its protected submission, exact submitted
script, and scheduler `COMPLETED/0:0` plus `Restarts=0` record. FROZEN at clocks
4250 and 4375 is an alias of the single p5 step-4000 evaluation, not another
generated sample or a relabeled checkpoint. Do not analyze partial task sets or
substitute inline mixed-policy evaluations for these endpoints.

### Known-cost checkpoint kernels

The additive known-cost checkpoint-kernel study uses its own content-addressed
13-task plan and commit-pinned control snapshot. Run readiness, dry-run/status,
dispatch, terminalization, and analysis only after sourcing the snapshot's
`activate_source_snapshot_eval.sh`. A canonical `kernel.json` is not a result by
itself: require the full intent/submission/release/GPU-terminal chain and the
plan-local `terminal_provenance.json`, which proves each dependent CPU
terminalizer also reached `COMPLETED/0:0`. Only then may
`analyze_known_cost_checkpoint_kernel.py analyze` write the primary summary and
immutable scientific-repeat decision. Technical retries never count as those
fresh-process repeats.

### Common failure modes

A few warnings are normal. Escalate when errors are persistent, growing, or hit a large fraction of rollouts.

- **Env workers**: exceptions in env code, timeouts, sandbox errors, OOM kills (most common source — runs user code).
- **Orchestrator**: empty/errored rollout spikes, weight-broadcast failures, checkpoint errors.
- **Trainer**: NCCL/CUDA errors, OOM, NaN loss or gradients.
- **Inference**: NCCL/CUDA errors, OOM, request timeouts.

### Process tree

All processes use `setproctitle` so they're visible in `ps`/`htop`/`pstree`:

```
PRIME-RL::Launcher
├── PRIME-RL::Inference          (vLLM server, GPU 0)
├── PRIME-RL::Orchestrator       (CPU-only)
│   └── Verifiers::EnvServer     (ZMQ env server per environment)
│       └── Verifiers::EnvWorker0..N
├── torchrun
│   └── PRIME-RL::Trainer        (GPU 1+)
└── tail trainer.log
```

For multi-node runs, trainer and inference processes are on separate nodes — use `srun` or `ssh` to inspect them.
