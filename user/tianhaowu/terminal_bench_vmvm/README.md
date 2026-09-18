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
  "env DATASET_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 MINIMUM_VALID=2500 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch" C-m
```

`run_oracle.py` writes one atomic JSON result per task plus `results.jsonl` and
`summary.json`. A resumed invocation skips existing terminal results unless
`RERUN_INVALID=1`. The full-corpus acceptance gate is at least 90% and at least
2,500 valid tasks; task failures must be debugged separately from VMVM
infrastructure failures.

Strict oracle validation applies the declared agent policy to `solve.sh` and
is the default. Some legacy reference solutions download build dependencies
despite declaring agent `no-network`. For corpus qualification only, set
`ORACLE_SOLUTION_NETWORK_MODE=public`: this leaves the trusted image startup
and reference solution on the setup bridge, records the override in immutable
run semantics and task/summary provenance, then activates the declared policy
before artifact collection and verification. It never changes model rollouts.
Report this compatibility result separately from the strict-policy result, and
use a fresh output directory when changing modes.

The adapter resolves Harbor's environment, agent, and verifier network policy
with Harbor 0.14.0 precedence. For `no-network`, trusted dependency staging
finishes first; immediately before untrusted agent or verifier execution, VMVM
moves all workload containers onto a private internal IPv4 network. Compose
aliases remain available, while a subnet-scoped firewall permits only internal
DNS and the main container's active reverse-tunnel port and rejects the gateway
proxy and other host traffic. Unknown modes, allowlists, IPv6, residual public
attachments, and attempts to relax an active policy fail closed.

Shared offline verifiers prefetch their declared dependencies before any agent
phase even when the agent itself is public. Prefetch accepts wheels only
(`--only-binary=:all:`), so package build hooks cannot execute during trusted
setup; source-only requirements fail closed. Cached controller archives are
read-only and tied to the taskset lifetime, per-runtime references are removed
on every terminal path, and evaluator shutdown deterministically deletes the
cache. Hidden tests are staged only after verifier network isolation; sandbox
wheelhouse copies are removed after use.

The old Mobius images do not contain every test-only package named by their
verifier scripts. The adapter extracts only literal exact
`name[extras]==version` pins from direct `pip install` commands in
`tests/test.sh` and prefetches the full merged requirement set before the
untrusted phase. The sole compatibility exception normalizes bare `pytest` to
the adapter's existing `pytest==8.3.4` pin. Other dynamic, URL, local-path,
unpinned, environment-marked, conflicting, and option-dependent specifications
fail closed rather than being replayed with different semantics. Offline
restoration re-probes the full dependency closure, runs as harness root without
`--ignore-installed`, and is revalidated from the task shell.

After materializing corpus revision `ac1f30b9a`, revalidate the 42 repaired
fixtures before consuming the prior 2,500-task manifest:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "env TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/validate/mobius_repaired_tasks.txt OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_repairs_ac1f30b9 DATASET_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9 MINIMUM_PASS_RATE=1 MINIMUM_VALID=42 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch" C-m
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

After `fetch_tb4.sh` verifies the prebuilt release, wait for every intended
route to be healthy, zero routes to be unhealthy, and a clean per-route
semantic plus state-reuse soak. Never treat `/health` alone as readiness.

### Shared 24-route Kimi deployment

The preferred `shared-kimi-k3` deployment publishes 24 sticky Kimi-K3 routes
and its credential through `proxy_info.json`. The readiness gate must establish
exactly 24 healthy routes, zero unhealthy routes, stable per-session affinity,
and clean one-token state reuse before the transcript smoke or full run starts.
The evaluator automatically sends both stable rollout-session headers. Pass the
credential file only; do not set `INFERENCE_DEPLOYMENT_ID` because this proxy
already has a default Kimi-K3 deployment.

After the approved two-task transcript smoke and strict trace audit pass, submit
one fresh pass@1 run. The dedicated config uses 24 rollout and HTTP slots, keeps
VMVM lease/tunnel setup capped at two, preserves the 256K total context budget,
and allows a queued model call up to 15,000 seconds without changing the
existing VMVM session or rollout deadlines.

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /path/to/clean/prime-rl-worktree && env -u INFERENCE_BASE_URL -u INFERENCE_DEPLOYMENT_ID -u INFERENCE_JOB_ID -u INFERENCE_PROXY_URL -u RESUME_DIR PROJECT_DIR=\$PWD EVAL_APPROVED_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_qwen_a95b_miniswe.tasks.txt EVAL_APPROVED_TASK_FILE_SHA256=9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892 EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_shared24_miniswe.toml INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/shared-kimi-k3/proxy_info.json OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_shared24_full_v1 VACLI_MAX_CONCURRENT_LEASES=2 sbatch --parsable --time=7-00:00:00 user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

Every real launch and resume through `run_eval.sbatch` requires an external
approved task file plus its lowercase SHA-256. The launcher snapshots the
selection, binds the source and resolved configs to that digest and task count,
records approval metadata in provenance, and rejects inline tasks or CLI
overrides. Exact `--dry-run` is the sole approval-free mode and exits before
task loading. The checked-in full-TB4 manifest is shared by the Kimi and Qwen
configs despite its historical filename.

`INFERENCE_PROXY_INFO` is the preferred interface for a direct RAM deployment:
the compute job reads `url` and `api_key` without putting the key in the config,
submission command, or provenance file. Do not set `INFERENCE_DEPLOYMENT_ID` for
a per-deployment proxy. Set it only when using a shared gateway route.

For a shared gateway route with no default deployment, also set
`INFERENCE_DEPLOYMENT_ID`; the launcher passes it as `X-Deployment-Id` without
embedding any credential in the config. For an HTTPS ingress that is reachable
only through the corporate forward proxy, set `INFERENCE_PROXY_URL` as well;
direct VMVM and inference routes continue to run with proxy variables cleared.

The shared config is `configs/eval/tb4_kimi_k3_shared24_miniswe.toml`: 66
tasks, pass@1, mini-swe-agent, `reasoning_effort=max`, one VMVM per rollout,
and a 256 Ki-token total context cap. It uses rollout concurrency 24 and an
HTTP connection/keepalive pool of 24. Keep vacli lease bring-up bounded at two
for this qualification run. All 11 TB4 tasks that declare Docker Compose
sidecars use the compose-capable VMVM path;
they are not skipped or downgraded to a single-container approximation. The
current VMVM tenant is CPU-only, so the three TB4 GPU tasks are rejected
explicitly instead of being run under a silently incorrect CPU sandbox; the
exact VMVM subset is therefore 63 tasks.

The Kimi configs explicitly give mini-swe-agent 10 total attempts for each
provider call. If all of those attempts fail, the full TB4 and Mobius configs
retry the whole rollout up to twice under a new trace/session ID; this can move
the retry away from a transiently bad sticky backend. The transparent
`EvalClient` itself does not own a retry loop.

The evaluator and oracle are network-bound CPU controllers; their checked-in
Slurm defaults request `cpu_x86`, 8 CPUs, 16 GiB, and no GPUs. Rollout
concurrency does not require one controller CPU per sandbox.

The single-route `tb4_kimi_k3_max_miniswe.toml` remains available only for the
digest-pinned `tianhaowu-k3-kda-tb1-low-20260916` fallback. It stays at four
rollout and HTTP slots and must pass its own one-route readiness gate before
use.

### Two-worker direct fallback

When the 24-route RAM deployment is unavailable, the checked-in direct-worker
fallback keeps every trajectory on one engine by construction. It is one
pass@1 evaluation split into two disjoint 33-task manifests, not two attempts
of the same tasks:

- `tb4_kimi_k3_direct_a.toml` uses `http://g3-138-137:32317/v1`, four rollout
  slots, and task-manifest SHA-256
  `d0f7c0297a82edf79f3e966ffd830fb418ea90c9faa7c4f3d288d5c7bacd1365`;
- `tb4_kimi_k3_direct_b.toml` uses `http://g3-146-243:32499/v1`, four rollout
  slots, and task-manifest SHA-256
  `485c1a038efc72a4eddf4928758c74d31827ebb7624108cee63e503df0fa02ec`.

The manifests contain 33 unique tasks each, have no overlap, cover all 66 TB4
tasks, and distribute the three CPU-unsupported GPU tasks as one plus two. The
supported tasks were greedily balanced using the completed TB4 oracle runtime.
Direct worker access requires all proxy environment variables to be unset;
`run_eval.sbatch` already does this. Do not set `INFERENCE_PROXY_URL` or put
these URLs behind round-robin routing. `OPENAI_API_KEY=EMPTY` is accepted.

The first full attempt used 16 rollouts per worker (32 aggregate). Jobs
`1733765` and `1733766` produced 19 tunnel-exposure failures and five Compose
failures; 11 of the first 13 rows were errors. They were canceled, as was
dependent merge `1733767`. Treat all three `_v1` directories as diagnostic and
do not resume or merge them. The measured fallback limit is now four rollouts
per worker (eight aggregate) and two concurrent lease bring-ups per controller
(four aggregate).

Submit only through the launcher tmux after both workers pass a fresh
no-logprob semantic and model-I/O smoke:

As of 2026-09-16 09:52 UTC both pinned ports refused TCP connections. Do not
submit these commands until both allocations are restored and pass the fresh
smoke. All replacement paths are `_v3`; canceled `_v1`/`_v2` artifacts are not
resume inputs.

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /storage/home/tianhaowu/prime-rl && env OPENAI_API_KEY=EMPTY EVAL_APPROVED_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_direct_a.tasks.txt EVAL_APPROVED_TASK_FILE_SHA256=d0f7c0297a82edf79f3e966ffd830fb418ea90c9faa7c4f3d288d5c7bacd1365 INFERENCE_BASE_URL=http://g3-138-137:32317/v1 EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_direct_a.toml OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_direct_a_v3 VACLI_MAX_CONCURRENT_LEASES=2 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m

tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /storage/home/tianhaowu/prime-rl && env OPENAI_API_KEY=EMPTY EVAL_APPROVED_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_direct_b.tasks.txt EVAL_APPROVED_TASK_FILE_SHA256=485c1a038efc72a4eddf4928758c74d31827ebb7624108cee63e503df0fa02ec INFERENCE_BASE_URL=http://g3-146-243:32499/v1 EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_direct_b.toml OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_direct_b_v3 VACLI_MAX_CONCURRENT_LEASES=2 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

Each shard remains its own resumable evaluator output. A resume replays the
saved direct URL and takes no overrides; never resume a shard against the other
worker. After both finish, publish a separate, audit-only combined artifact:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/combine_tb4_shards.py \
  --shard-a-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_direct_a_v3 \
  --shard-b-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_direct_b_v3 \
  --output-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_direct_combined_v3 \
  --dataset-dir /checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0/tasks
```

The combiner takes both evaluator writer locks, validates the committed and
snapshotted task/config hashes, exact worker URLs, matching code revisions,
33-row shard membership, and cross-shard trace IDs. It then runs the strict
66-task TB4 reasoning/model-I/O/KDA/score audit in a temporary directory and
atomically publishes `results.jsonl`, `checkpoint.json`, and
`merge_manifest.json` only when every check passes. The combined directory is
not resumable because task indices are local to each shard; resume the source
shards instead.

### Qwen 16-worker direct fallback

The shared Qwen proxy has a shorter upstream request deadline than the Qwen
evaluation client. `run_qwen_direct_eval.sbatch` bypasses it by starting a
loopback-only `vllm-router` from the 16 pinned worker metadata files under
`shared_qwen38_2p4t/endpoints`. The launcher requires the exact deployment spec
and endpoint-bundle hashes, probes `/health` and `/v1/models` on every worker,
and refuses to start until the local router reports all 16 workers active. It
does not read `proxy_info.json` or accept a real API key.

The router dependency is an isolated optional group and must not be added to
the live evaluator dependency directory. Once no active evaluation depends on
that directory, stage it at its separate versioned path:

```bash
bash user/tianhaowu/terminal_bench_vmvm/stage_qwen_direct_router.sh
```

The router disables retries and uses consistent-hash dispatch across the 16
pinned workers, keyed only by `x-session-id`. Verifiers sends the same
`X-Session-ID` trace ID on every turn of a rollout, so its growing prefix stays
on one worker instead of losing KV-cache locality on every round-robin hop. The
production admission epoch uses a 32-connection shared HTTP pool, a router
bucket of 32 requests, and a 32-request
queue for production concurrency 64, with a 7,200-second queue timeout and a
7,500-second backend request deadline. Because vllm-router 0.1.26 refills that
bucket while requests are still active, the shared evaluator HTTP/1.1 pool—not
the bucket—is the strict backend bound. This keeps 64 rollout/VMVM sessions
active while at most 32 model calls reach the router. Manifest schema 3 records
the rollout, client, router, and queue limits together; resume rejects the old
production cap-16 schema until it is migrated through the COW admission edge.
The production mini-swe
model timeout is 15,000 seconds, covering a full 7,200-second local pool wait
plus a full provider read with margin while remaining below the rollout limit.
Simultaneous VMVM lease or reverse-forward setup is capped at two for the
production canary; the shared slot is released after setup, not held for the
tunnel lifetime.

The full 66-task TB4 set and 2,500-task oracle-valid Mobius production set,
including all task categories, are approved for the direct Qwen route. The
checked-in launch inputs are:

- `tb4_qwen_token_smoke.toml`: two tasks from
  `tb4_qwen_token_smoke.tasks.txt`, SHA-256
  `4ae515a77f33746ecb598ab6c670612265bd1ef726eb6ca7f16cc81f5e191c25`;
- `tb4_qwen_a95b_miniswe.toml`: all 66 TB4 tasks from
  `tb4_qwen_a95b_miniswe.tasks.txt`, SHA-256
  `9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892`;
- `mobius_qwen_a95b_2500.toml`: the 2,500 oracle-valid Mobius tasks from
  `mobius_valid_tasks_2500.txt`, SHA-256
  `d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b`.

The smoke uses two slots, TB4 uses eight, and the Mobius production config uses
64. Multiplexing matches rollout concurrency; the production shared HTTP pool
is explicitly pinned to 32. Every config retains
captured model I/O and thinking content, permits 32,768 output tokens per model
call, and keeps the 262,144-token full-context cap plus the extended VMVM
timeouts.
The direct launcher still requires the selected manifest path and exact digest
to be supplied independently through `DIRECT_QWEN_APPROVED_TASK_FILE` and
`DIRECT_QWEN_APPROVED_TASK_FILE_SHA256`. `EVAL_CONFIG` must select that same
hash using `task_file` plus `task_file_sha256` while omitting inline `tasks`.
The launcher hashes both files without printing or otherwise exposing their
contents.

After an approved run is terminal, first invoke `direct_qwen_workers.py
--audit-run-dir RUN_DIR`; it validates the non-secret worker manifest, saved
loopback URL, config snapshot, admission contract, and credential-free
provenance without opening the results file for a fresh schema-3 run. For a
migrated run it additionally hashes result rows, without printing their
content, to prove the epoch-1 and epoch-2 membership certificates. Then invoke
`audit_traces.py` with both
`--expected-task-file APPROVED_ALLOWLIST` and the approved expected count. Both
commands emit summaries only; do not print result rows. Resume only through
`run_qwen_direct_eval.sbatch`, which reuses the snapshotted endpoint set and
local port and fails if the live metadata no longer exactly matches.

The active direct-worker manifest schema is version 3. It binds rollout
concurrency 64, both client connection limits 32, router admission 32, and
queue size 32 in one explicit admission record. It also binds both
`policy = consistent_hash` and the exact singleton
`request_id_headers = ["x-session-id"]`; the launcher obtains those values from
the validated manifest-derived runtime file and checks them again before
starting the router. Historical schema-1 round-robin and schema-2 cap-16
outputs are deliberately not directly resumable with this launcher. Do not
edit their manifests in place or present mixed routing/admission epochs as one
epoch. See `QWEN_ROUTING_MIGRATION.md` for the required copy-on-write
transition certificates when preserving prior good rows.

## Transcript capture gate

Never request provider log probabilities in this workflow. RAM issue `#279`
records a Kimi Rust-frontend crash (`token_ranks must be >=1`) when a request
asks for logprobs. All checked-in eval configs therefore omit `logprobs`,
`prompt_logprobs`, `top_logprobs`, and `return_token_ids` entirely. The
chat-completions dialect still preserves assistant response content, tool calls,
`reasoning_content`, and provider usage. These are durable text transcripts for
offline retokenization/processing, not directly consumable token-level on-policy
samples; original sampling log probabilities cannot be reconstructed offline.

This request-side rule contains the worker-wide dispatcher outage but does not
by itself cure silent KDA state-reuse corruption. The active stock-image
fallback disables prefix caching so cache hits cannot create a one-token first
chunk and serializes each backend with `max-num-seqs=1`; it also disables the
Rust frontend and uses `PIECEWISE` CUDA graphs. This is an operational
workaround, not the source-level fix from vLLM PR `#51483`, so a green
`/health` still requires a clean state-reuse semantic soak over every route.

After verifying the frozen isolation and PIECEWISE settings, run the
standalone semantic snapshot and sticky-route gate before the two-task smoke.
It reads the proxy URL, key, served model, and sticky/Redis metadata directly
from `proxy_info.json`, never includes the key in its JSON output, and uses only
the Python standard library. Each discovery request gets a unique session value in both
`X-LiteLLM-Session-ID` and `X-Session-ID`; the probe then repeats one stable
session sequentially per backend and requires `x-litellm-model-api-base` to
remain fixed.

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/probe_inference_routes.py \
  --proxy-info /checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb24-nocache-20260916/proxy_info.json \
  --model Kimi-K3 \
  --expected-routes 24 \
  --requests 192 \
  --repeats 3 \
  --concurrency 24 \
  --health-timeout 30 \
  --timeout 300 \
  --max-tokens 4096 \
  --require-reasoning \
  --pretty
```

Set `--expected-routes` to the deployment's intended ready-route count, not
merely its current observed count. The command requires the model-specific
health response to report exactly that many healthy routes and zero unhealthy
routes before and after the requests. It also requires an exact observed route
count, shared-affinity metadata, no hidden LiteLLM retries, an exact marker with
a normal stop, and stable backend headers for the repeated sessions. It then
runs serial raw-completion predecessor/one-token-target cycles on every
discovered backend and fails if routing changes, the target prompt or response
is not exactly one token, corruption appears, or deterministic target output
depends on predecessor state. Neither request dialect sends `logprobs`,
`prompt_logprobs`, `top_logprobs`, or `return_token_ids`; the summary never
contains response text. `--allow-unverified-affinity` and `--skip-health` exist
for diagnosis only and must not be used for the production readiness gate.

The Kimi production config uses the committed, portable oracle-qualified
manifest at
`configs/eval/mobius_valid_tasks_2500.txt` (49,334 bytes, 2,500 lines,
SHA-256
`d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b`).
The launcher snapshots and hash-checks it before the production run:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /storage/home/tianhaowu/prime-rl && env EVAL_APPROVED_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_valid_tasks_2500.txt EVAL_APPROVED_TASK_FILE_SHA256=d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_kimi_k3_max_2500.toml INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/proxy_info.json OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/mobius_kimi_k3_max_2500_transcript_v2 VACLI_MAX_CONCURRENT_LEASES=4 sbatch --parsable --time=7-00:00:00 user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

The checked-in production starting point is eight active rollouts and four
simultaneous lease starts. Qualify it with the patched full TB4 run, then use
audited capacity smokes to raise steady-state concurrency to 16 and at most 24
after the deployment has 24 ready routes; keep lease starts at four. Update the
config before creating the production output directory because a resume replays
its saved config verbatim. The oracle-only 64/32 result does not qualify model
trace generation: it has no per-rollout model-interception tunnel or Compose
sidecars.

Interrupted evals are durable. Resume only their missing or errored rollouts
with
`RESUME_DIR=/checkpoint/.../evals/mobius_kimi_k3_max_2500_transcript_v2`, the
same `EVAL_APPROVED_TASK_FILE{,_SHA256}` pair, and the same
`INFERENCE_PROXY_INFO=.../proxy_info.json`; the latter is required to reload the
RAM API key because credentials are deliberately absent from saved config and
provenance. A resume replays the saved proxy URL, so confirm that the same
deployment proxy is still live before submitting it.
The saved config is replayed verbatim and successful traces are retained. New
runs snapshot the source config, task list, and image manifest under
`OUTPUT_DIR/inputs/`, record SHA-256 digests in `inputs/manifest.json`, and point
the resolved run config at those immutable copies. Large configs set
`retain_traces=false`: every trace is appended durably and then released from
RAM, and the CLI does not duplicate the full JSONL into the Slurm log.

The Kimi Mobius config additionally requires the dataset worktree to be clean
at exact commit `ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366`, the task manifest to
have SHA-256 `d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b`,
and the image manifest to have SHA-256
`118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009`.
Task loading fails before any model call if the checkout is moved or dirty, or
if either manifest differs.

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
turn over 262,144 total tokens. When model-I/O capture is required, it also
normalizes every captured chat request and proves that its message list exactly
matches the persisted root-to-parent graph path, including historical reasoning,
tool calls, and tool results. `--require-token-data` remains an explicit
legacy/diagnostic mode for traces that intentionally contain exact token IDs,
masks, and sampling logprobs. Scale only after the default gate passes on a
fresh smoke run and after measuring stable VMVM lease concurrency.

A sampled tool-call turn may omit flattened reasoning only when its hash-bound
provider response proves either a zero `reasoning_tokens` count or an explicit
empty reasoning field. The explicit-empty case additionally requires an exact
provider response, identical captured and flattened tool calls, and a
hash-valid reconstructed request with both thinking and thinking preservation
enabled; a missing field is not evidence of emptiness. The audit reports these
as separate `provider_reported_zero_reasoning_tool_turns` and
`provider_explicit_empty_reasoning_tool_turns` counters. A trace containing no
sampled reasoning anywhere still fails closed.

Because this workflow intentionally omits token IDs, the previous response's
provider usage is used as the conservative best-known size when clamping the
next generation budget. Exact token arrays remain authoritative whenever they
are present. New tool output can still increase the next prompt beyond that
known prefix, so the provider usage returned for every response remains the
final fail-closed check: a turn above 262,144 tokens is rejected before graph
commit and cannot enter the retained training corpus.

## SFT export

`results.jsonl` is the immutable source transcript, not a directly loadable SFT
dataset. After the evaluation is terminal, export either reward-one traces or
all scored outcomes explicitly:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/export_sft.py \
  /path/to/eval/results.jsonl \
  --output-dir /path/to/new/sft-dataset \
  --selection pass-only \
  --expected-count 2500
```

For a migrated Qwen run, create its final routing-epoch index only after the
last evaluator job is terminal, then consume it explicitly:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/export_sft.py \
  /path/to/migrated-run/results.jsonl \
  --output-dir /path/to/new/sft-dataset \
  --selection pass-only \
  --expected-count 2500 \
  --routing-epoch-index /path/to/private-sidecars/qwen_router_epochs.jsonl
```

For a production routing-epoch-3 run, use the terminal finalizer instead of
issuing those two commands independently. It requires explicit, disjoint
source and output boundaries; an exact clean Prime-RL revision; the expected
source provenance digest; the terminal row count; selection; and split policy.
It refuses relative, symlinked, broad, overlapping, or default paths, held
writer/router locks, an existing output, nonterminal recorded jobs, and any
routing/provenance mismatch. It creates the routing index in a private staging
directory, passes that exact index to `export_sft.py`, retains it in the
published corpus, and never writes to the source run. The complete corpus is
published only after all repository, provenance, and artifact checks pass.
Child output is captured and reduced to aggregate counts, hashes, or stable
error codes.

Submit from a clean detached x86-capable source snapshot at the finalizer's
exact commit. The source/output root directories must already exist. Replace
the angle-bracketed values with audited literal values; do not use command
substitution in the submission command:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "sbatch --dependency=afterok:PRODUCER_JOB_ID --export=ALL,FINALIZER_PROJECT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-FINALIZER_SHA,FINALIZER_EXPECTED_REVISION=FINALIZER_REVISION_40_HEX,FINALIZER_SOURCE_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals,FINALIZER_SOURCE_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/EPOCH_3_RUN,FINALIZER_EXPECTED_PROVENANCE_SHA256=PROVENANCE_SHA256_64_HEX,FINALIZER_OUTPUT_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft,FINALIZER_OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft/FINAL_EXPORT,FINALIZER_EXPECTED_COUNT=2500,FINALIZER_SELECTION=pass-only,FINALIZER_VALIDATION_PERMYRIAD=500,FINALIZER_SPLIT_SALT=terminal-bench-vmvm-sft-v1 /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-FINALIZER_SHA/user/tianhaowu/terminal_bench_vmvm/finalize_qwen_sft.sbatch" C-m
```

Slurm copies the wrapper at submission and `afterok` prevents it from starting
before the evaluator succeeds. The finalizer independently requires every job
recorded in the source provenance to be terminal, rechecks the clean code
revision and provenance digest between stages, and never overwrites an index or
dataset. A partial failure after index publication therefore requires an
explicit aggregate audit before any operator chooses a new output path; do not
blindly rerun or remove artifacts.

### Qwen missing/error repair chain

Do not resume a terminal production Qwen source in place to repair missing or
errored rows. Use `run_qwen_repair_chain.sbatch` from a clean detached checkout
at the exact controller revision. The controller derives the approved task file
only from the immutable source snapshot, requires its externally supplied
SHA-256 and exactly 2,500 opaque entries, and uses the pinned resume planner to
select missing/error indices plus scored passes that fail the exact SFT
trainability audit. Scored failures are retained in the original source and
are not regenerated. A decode-failing final fragment without a newline remains
in the immutable source digest but is omitted from the logical row stream and
left owed; complete malformed rows fail closed, while a valid final JSON object
remains a logical row even without a newline. The chain performs no semantic
task inspection, classification, or name-based filtering.

The controller creates a fresh schema-3 direct run inside a private runtime
directory, with 64 rollout sessions, a 32-request provider/router cap, a
32-request queue, and a 262,144-token total context cap. It invokes
`run_qwen_direct_eval.sbatch` as a shell program in the controller's existing
allocation; it never submits a child Slurm job. The original and repair sources
are hash-checked before and after every subsequent stage. Pass-only original
and repair exports are published atomically, then `merge_qwen_sft.py` publishes
the final corpus atomically after proving the exports are disjoint and bound to
the same split contract. Repair traces are name/index-bound to the evaluator
order of the approved repair universe. The controller passes the exact
post-finalization manifest and complete tree digests for both exports to the
merger, which rejects later mutation and any repair task outside the selected
union; every selected strict-invalid pass must still be replaced. Existing
runtime or output paths are always rejected.
The repair export keeps mode-0600 copies of the selection manifest and repair
attestation beside the four base SFT artifacts; the merger requires both
copies to be byte-identical to the externally hash-pinned inputs and binds
their digests into the merged manifest.

If the planner finds zero owed rows, the controller publishes only the original
pass-only export and returns `finalized_without_repair`; the repair and merged
destinations remain absent. Otherwise success is `merged`, and all three export
directories are present. A failed intermediate stage can leave an attested
original or repair export, but never a final merged directory; use fresh paths
for another attempt and do not delete or overwrite the evidence.

All child stdout and stderr are retained under the private runtime directory as
mode-0600 logs. Scheduler output contains only aggregate counts, SHA-256 values,
and stable error codes. It never forwards task identifiers, prompts, trace rows,
model responses, reasoning, tool payloads, or child errors.

Submit only through `swebench_vmvm:Launcher.0`, after replacing every uppercase
placeholder with an audited literal. Use `afterany` because a terminal producer
may legitimately contain the missing/error rows that this chain repairs. The
three roots must already exist and must be absolute, pairwise-disjoint, narrow
boundaries; every attempt and output directory must be new.

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "sbatch --parsable --dependency=afterany:PRODUCER_JOB_ID --export=ALL,QWEN_CHAIN_PROJECT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-CONTROLLER_SHA,QWEN_CHAIN_EXPECTED_REVISION=CONTROLLER_REVISION_40_HEX,QWEN_CHAIN_SOURCE_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals,QWEN_CHAIN_SOURCE_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/ORIGINAL_RUN,QWEN_CHAIN_APPROVED_TASK_FILE_SHA256=APPROVAL_SHA256_64_HEX,QWEN_CHAIN_EXPECTED_PROVENANCE_SHA256=PROVENANCE_SHA256_64_HEX,QWEN_CHAIN_RUNTIME_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/repair-runtime,QWEN_CHAIN_RUNTIME_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/repair-runtime/ATTEMPT,QWEN_CHAIN_OUTPUT_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft,QWEN_CHAIN_ORIGINAL_EXPORT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft/ORIGINAL_EXPORT,QWEN_CHAIN_REPAIR_EXPORT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft/REPAIR_EXPORT,QWEN_CHAIN_MERGED_OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sft/MERGED_EXPORT,QWEN_CHAIN_VALIDATION_PERMYRIAD=500,QWEN_CHAIN_SPLIT_SALT=terminal-bench-vmvm-sft-v1 /checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-CONTROLLER_SHA/user/tianhaowu/terminal_bench_vmvm/run_qwen_repair_chain.sbatch" C-m
```

With that option, the exporter requires an exact one-to-one row-hash mapping,
binds the full results, index, policy transition, active router manifest, and
transition-anchored epoch-1 hash list. For a schema-3 admission run it also
validates the complete cap-32 transition chain and binds the admission
certificate plus the epoch-2 lineage. Each epoch label is checked against the
anchored lineage before any output is published. Every emitted SFT row and the
aggregate manifest carry its routing epoch. Omit the option for a non-migrated
run; no routing-epoch field is then added.

Use `--selection all-outcomes` only when failed trajectories are intentionally
part of the training recipe. The exporter refuses held evaluator or
direct-router locks, an existing output, provenance drift, and malformed or
errored source structure. Every row is still covered by source/index identity,
duplicate, error-list, completion, reward, and stop-condition validation.
Error rows are counted and excluded. Under `pass-only`, scored failures are
also counted and excluded before the strict trainability audit; only traces
eligible for the output corpus can therefore block it for missing reasoning,
model I/O, or usage. `all-outcomes` applies that strict audit to both passing
and failing scored traces. Selected traces fail closed on request or response
hash corruption and any provider-reported sequence over 262,144 tokens. The
exporter also requires every captured chat request to match the persisted graph
prompt, then validates each retained assistant message, finish reason, and usage
against the captured provider response. Only the exact `/chat/completions`
route is accepted. Assistant `content` may be absent when Verifiers'
`exclude_none` serializer omits it. Unknown message fields/content parts,
non-null `provider_state` or `reasoning_details`, and sampled finish reasons
other than `stop` or `tool_calls` are rejected because the current SFT renderer
cannot preserve those states faithfully. Tool definitions require the
canonical OpenAI `type="function"` envelope and null-free JSON Schema values.
Tool-call arguments must be duplicate-free, finite, null-free JSON objects.
The loader removes only null padding introduced by Arrow's cross-row struct
widening.

One output row represents one unique sampled assistant node and its root-to-node
message path. This preserves every genuine generation exactly once even when a
trace branches; expanding every leaf would duplicate shared-prefix targets.
Prior messages are explicitly non-trainable and prior assistant reasoning is
retained verbatim. The final assistant is the sole trainable message. Every
sampled assistant keeps its authentic `reasoning_content` and `finish_reason`;
the row records source-versus-retained fidelity counts, while content and tool
calls are retained as before. Verifiers' compact tool calls are normalized to
OpenAI function-call objects, and the stable tool schema comes from
integrity-checked captured requests.

The output is atomically published as `train/train.jsonl`,
`validation/train.jsonl`, `task-split.json`,
`target-rendering-contract.json`, and `manifest.json`, plus the validated
routing-index sidecar when one is supplied. The immutable rendering contract
pins the Nemotron Super tokenizer revision, renderer repository revision, and
the exact `nemotron-3` settings that preserve all historical thinking; export,
finalization, and merge reject a changed contract. Task identity is the
SHA-256 of the taskset ID, dataset revision, and explicit approved
task slug separated by NUL bytes; changing a run-local task index does not
change its split. The manifest binds the raw results, resolved and source
configs, approved task snapshot, image snapshot, input manifest, launcher
provenance, exporter source, and every output artifact. Console output contains
aggregate counts and hashes only.

The exported messages are intended for offline retokenization by the target SFT
renderer. They do not recreate teacher token IDs or sampling log probabilities,
which were deliberately not requested from the evaluation endpoint.

Before training format-v3 output, run the rendering preflight from the exact
clean, detached Prime-RL revision that will launch the trainer:

```bash
uv run python user/tianhaowu/terminal_bench_vmvm/preflight_sft.py \
  --export-root /absolute/path/to/corpus \
  --expected-manifest-sha256 MANIFEST_SHA256 \
  --project-dir /absolute/path/to/prime-rl \
  --expected-project-revision PRIME_RL_COMMIT \
  --output /absolute/path/to/corpus/sft-render-preflight.json
```

The command renders every row, verifies that retained reasoning changes the
token stream and target reasoning changes trainable tokens, proves the loss
mask matches the selected assistant's renderer attribution, and rejects a
rendered row over 262,144 tokens. It records only aggregate counts and hashes.
Pin the resulting file and digest in every format-v3 train or validation data
block with `preflight_attestation` and
`preflight_attestation_sha256`. The trainer rehashes the attestation, export
manifest and all declared artifacts, then independently rerenders every row and
rechecks the Prime-RL revision, loader sources, renderer gitlink,
rendering/tokenization dependency versions, tokenizer revision, renderer
config, loss mask, data path, and sequence length before model setup.
Format-v3 rows are also rejected in the dataset loader unless this startup gate
has succeeded. The target tokenizer block must use the repository and revision
from `target-rendering-contract.json`, with `trust_remote_code = false`; the
renderer block must exactly match its `renderer.config` object.

```toml
[tokenizer]
name = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"
revision = "d51eab0d1f979ebc26b546e634a04f450d99158e"
trust_remote_code = false

[data]
type = "sft"
name = "/absolute/path/to/corpus/train"
seq_len = 262144
pack_function = "fixed_stack"
preflight_attestation = "/absolute/path/to/corpus/sft-render-preflight.json"
preflight_attestation_sha256 = "PREFLIGHT_SHA256"
```
