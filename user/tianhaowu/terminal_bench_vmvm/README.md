# Terminal-Bench on VMVM

This directory contains the Prime-RL v1 Harbor adapter and operational scripts
for the 2,538 `mobius-tb/*` tasks and official Terminal-Bench 4.0.0. The
runtime is `VMVMRuntime`, which uses the hardened `vmvm_tb_v2`
vacli transport (lease retries, SSH reconnection, binary-safe transfers, and
bounded command output).

The VMVM backend defaults to `/public/fbpkgs/x86_64/vacli/stable/vacli`.
The moving `latest` build was rejected because its x2p helper fails with a
GLIBC-version error on part of the heterogeneous `cpu_x86` fleet. Override
`VACLI_BIN` only for a canary that has passed `probe_vmvm.sbatch`.

Correctness invariants:

- An infrastructure failure is never converted into reward zero.
- Shared-verifier tasks retry the whole rollout after `SandboxError` or
  `TunnelError`; verifier code cannot replay a model command.
- Separate-verifier tasks capture artifact bytes once and may retry only a
  fresh verifier VMVM against those identical bytes.
- Image tags are immutable corpus revisions, never `latest`.
- Oracle and rollout outputs have one writer and are durable while a run is in
  progress.
- Compose tasks run the declared sidecars inside the same VMVM lease. Artifact
  collection addresses the declared service, and the exact captured bytes are
  replayed into a fresh verifier VMVM.
- Oracle validity is determined by the task verifier. A nonzero reference
  script status is retained as a warning because some separate-mode scripts
  emit the correct artifact before an optional self-check that needs
  verifier-only code.

## Pinned inputs

- Mobius corpus: Prime-RL commit `ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366`
  (2,538 immediate child task directories, including the validated fixture
  repairs on top of corpus commit `9b6988a3faf0f58f8f6719abef51c60dc257586c`).
- TB4: `harbor-framework/terminal-bench` commit
  `452bf305c6daa62fc59061d22133a7cbc7c1572e` (`v4.0.0`, 66 tasks) and its
  official prebuilt release archive SHA-256
  `6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e`.
- Harbor harness: `0.14.0`.
- mini-swe-agent harness: `2.2.8`.

## One-time CPU setup

The login node is ARM64 and `cpu_x86` nodes are x86_64. Do not reuse
`~/.local/bin/uv` on compute nodes. Install the official x86 uv binary under
`~/.local/x86_64/bin`, then stage target-platform dependencies from the
networked login host:

```bash
bash user/tianhaowu/terminal_bench_vmvm/stage_x86_dependencies.sh
bash user/tianhaowu/terminal_bench_vmvm/fetch_tb4.sh
```

The dependency target defaults to
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64`. Slurm jobs add
the local source trees ahead of it in `PYTHONPATH`, so code edits take effect
without rebuilding that layer.

`vmvm-sandbox` intentionally does not check out the 2,538 task directories.
Materialize the pinned repaired corpus as a detached worktree instead:

```bash
git fetch origin feat/tb4-vmvm-pipeline
git worktree add --detach \
  /checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 \
  ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366
```

The checked-in password-protected `tb_tasks.zip` matches the original corpus,
but not the later validated fixture repairs, so it is not the production
dataset source.

## Build images

First resolve the already-published Mobius images to immutable Docker Hub
digests. The resolver pages the public tag API, requires a Linux/amd64 image,
and verifies all 2,538 task slugs:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/resolve_dockerhub_images.py \
  --dataset-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 \
  --output /checkpoint/ram/tianhaowu/terminal_bench_vmvm/mobius_images.json \
  --require-all
```

The images currently live in `docker.io/tianhao0122/optimbench-tb`. The
taskset consumes the generated manifest and therefore pulls `tag@sha256`
rather than mutable tags. If coverage is incomplete, generate the deterministic
VMVM rebuild plan:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/prepare_build_plan.py \
  --dataset-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 \
  --output /checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_plan.jsonl \
  --image-prefix vmvm-registry.fbinfra.net/terminal_bench \
  --image-tag mobius-9b6988a3faf0

```

TB4 uses its official release bundle rather than rebuilding images. Its task
files point to digest-pinned Docker Hub images for the agent, verifier, and
sidecars.

Submit rebuilds, if any, as Slurm state changes from
`swebench_vmvm:Launcher.0`:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "sbatch --parsable --export=ALL,BUILD_PLAN=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_plan.tsv user/tianhaowu/terminal_bench_vmvm/build_images_vmvm.sbatch" C-m
```

Each worker holds one VMVM lease and builds its deterministic slice. Per-image
status files make the operation resumable without concurrent append races.
Audit before validation:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/audit_builds.py \
  --plan /checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_plan.jsonl \
  --require-all
```

## Oracle validation

Smoke one task first by putting its directory slug in a text file and setting
`TASK_FILE`. Then run the full set:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "env DATASET_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch" C-m
```

`run_oracle.py` writes one atomic JSON result per task plus `results.jsonl` and
`summary.json`. A resumed invocation skips existing terminal results unless
`RERUN_INVALID=1`. The full-corpus acceptance gate is at least 90% valid; task
failures must be debugged separately from VMVM infrastructure failures.

After materializing corpus revision `ac1f30b9a`, revalidate the 42 repaired
fixtures before consuming the prior 2,500-task manifest:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "env TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/validate/mobius_repaired_tasks.txt OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_repairs_ac1f30b9 DATASET_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch" C-m
```

Validate TB4 with its official digest-pinned images and Compose sidecars by
setting `USE_DECLARED_IMAGES=1` and `ENABLE_COMPOSE=1`:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "sbatch --parsable --export=ALL,DATASET_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0/tasks,USE_DECLARED_IMAGES=1,ENABLE_COMPOSE=1,MAX_CONCURRENT=8 user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch" C-m
```

The model-facing TB4 inputs remain byte-for-byte official. Oracle-only setup
applies one compatibility constraint for `cad-model`: `build123d==0.10.0`
allows newer `ocp_gordon` releases that require an incompatible OCP ABI, so the
reference run pins the last compatible `ocp_gordon==0.1.18`. This constraint is
not injected into agent rollouts or verifier containers.

## TB4 pass@1

After `fetch_tb4.sh` verifies the prebuilt release, wait for a KDA-patched Kimi
runtime, at least 16 healthy and zero unhealthy routes in the normal-QoS
deployment, and a clean per-route semantic soak. Then submit exactly one fresh
pass@1 run against Kimi-K3 in max-reasoning mode:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /storage/home/tianhaowu/prime-rl && env EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_max_miniswe.toml INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb16-normal-20260915/proxy_info.json OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_full_v2 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

`INFERENCE_PROXY_INFO` is the preferred interface for a direct RAM deployment:
the compute job reads `url` and `api_key` without putting the key in the config,
submission command, or provenance file. Do not set `INFERENCE_DEPLOYMENT_ID` for
a per-deployment proxy. Set it only when using a shared gateway route.

For a shared gateway route with no default deployment, also set
`INFERENCE_DEPLOYMENT_ID`; the launcher passes it as `X-Deployment-Id` without
embedding any credential in the config. For an HTTPS ingress that is reachable
only through the corporate forward proxy, set `INFERENCE_PROXY_URL` as well;
direct VMVM and inference routes continue to run with proxy variables cleared.

The default config is `configs/eval/tb4_kimi_k3_max_miniswe.toml`: 66 tasks,
pass@1, mini-swe-agent, `reasoning_effort=max`, one VMVM per rollout, and a
256 Ki-token total context cap. It uses rollout concurrency 64 and an HTTP
connection/keepalive pool of 64. The larger Mobius trace config uses the same
concurrency while vacli lease bring-up remains bounded at 32. All eight TB4
tasks that declare Docker Compose sidecars use the compose-capable VMVM path;
they are not skipped or downgraded to a single-container approximation. The
current VMVM tenant is CPU-only, so the three TB4 GPU tasks are rejected
explicitly instead of being run under a silently incorrect CPU sandbox; the
exact VMVM subset is therefore 63 tasks.

The evaluator and oracle are network-bound CPU controllers; their checked-in
Slurm defaults request `cpu_x86`, 8 CPUs, 16 GiB, and no GPUs. Rollout
concurrency does not require one controller CPU per sandbox.

## Transcript capture gate

Never request provider log probabilities in this workflow. RAM issue `#279`
records a Kimi Rust-frontend crash (`token_ranks must be >=1`) when a request
asks for logprobs. All checked-in eval configs therefore omit `logprobs`,
`prompt_logprobs`, `top_logprobs`, and `return_token_ids` entirely. The
chat-completions dialect still preserves assistant response content, tool calls,
`reasoning_content`, and provider usage. These are durable text transcripts for
offline retokenization/processing, not directly consumable token-level on-policy
samples; original sampling log probabilities cannot be reconstructed offline.

This request-side rule only contains the worker-wide outage. The same incident
also found silent KDA state-reuse corruption without logprobs, where a worker
returns repeated `@`/blank text with HTTP 200. A stock-image pool is therefore
not launch-ready merely because `/health` is green: it needs a compatible port
of vLLM PR `#51483`, `PIECEWISE` CUDA graphs (or eager mode), and a clean
state-reuse semantic soak covering every route.

Export exactly 2,500 oracle-qualified tasks before the production run:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/export_oracle_tasks.py \
  /checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_full \
  /checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_full/valid_tasks_2500.txt \
  --limit 2500

tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /storage/home/tianhaowu/prime-rl && env EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_kimi_k3_max_2500.toml INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb16-normal-20260915/proxy_info.json OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/mobius_kimi_k3_max_2500_transcript_v1 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

Interrupted evals are durable. Resume only their missing or errored rollouts
with
`RESUME_DIR=/checkpoint/.../evals/mobius_kimi_k3_max_2500_transcript_v1`;
the saved config is replayed verbatim and successful traces are retained. New
runs snapshot the source config, task list, and image manifest under
`OUTPUT_DIR/inputs/`, record SHA-256 digests in `inputs/manifest.json`, and point
the resolved run config at those immutable copies. Large configs set
`retain_traces=false`: every trace is appended durably and then released from
RAM, and the CLI does not duplicate the full JSONL into the Slurm log.

Before consuming any run, execute:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/audit_traces.py \
  /path/to/results.jsonl \
  --expected-task-file /path/to/oracle_passed_tasks.txt \
  --expected-count 2500 \
  --require-reasoning
```

Transcript audit is the default. It rejects missing/duplicate tasks, rollout
errors, missing sampled response content/tool calls, missing reasoning, invalid
or absent provider usage, malformed parent graphs, and any provider-reported
turn over 262,144 total tokens. `--require-token-data` remains an explicit
legacy/diagnostic mode for traces that intentionally contain exact token IDs,
masks, and sampling logprobs. Scale only after the default gate passes on a
fresh smoke run and after measuring stable VMVM lease concurrency.
