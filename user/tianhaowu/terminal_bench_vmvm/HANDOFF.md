# VMVM Terminal-Bench handoff

State captured on 2026-09-15 UTC. The takeover branch is `vmvm-sandbox`.

## Start here

```bash
cd /storage/home/tianhaowu/prime-rl
git fetch origin
git switch vmvm-sandbox
git pull --ff-only origin vmvm-sandbox
git submodule update --init --recursive
```

The parent repository pins `deps/verifiers` at `3b78e08e`. That verifier
revision preserves assistant responses and reasoning, makes large evals
durable, retries transient VMVM setup failures, and sends both `X-Session-ID`
and the LiteLLM-consumed `X-LiteLLM-Session-ID` from a stable rollout ID.

The target branch intentionally contains `tb_tasks.zip`, not the 2,538
expanded Mobius task directories. The archive matches original corpus commit
`9b6988a3f`, but the production corpus must include the validated repairs from
`ac1f30b9a`. A clean detached worktree is already materialized at
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9` and
contains all 2,538 tasks and all 2,500 selected slugs. Recreate it with
`git worktree add --detach PATH ac1f30b9a` if needed. The Mobius configs point
there; do not commit the expanded tasks or the archive password.

Before the production trace run, revalidate the 42 repaired fixtures using
`configs/validate/mobius_repaired_tasks.txt`; 34 of them are in the selected
2,500-task manifest. This proves the clean detached worktree reproduces the
repairs that were present during the successful oracle run.

## What is complete

- VMVM transport is hardened for lease retries, SSH reconnects, bounded output,
  binary-safe transfer, declared Compose sidecars, and Python-less images.
- TB4 v4.0.0 is pinned to commit
  `452bf305c6daa62fc59061d22133a7cbc7c1572e` and release SHA-256
  `6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e`.
- The 66-task Kimi config is pass@1, max reasoning, 64 rollout/HTTP concurrency,
  200 turns, and a 262,144-token total cap. Eight Compose tasks use the real
  multi-service path. Three GPU tasks are explicitly unsupported by the
  current CPU-only VMVM tenant, leaving 63 CPU-supported tasks.
- All five model-eval configs omit `logprobs`, `prompt_logprobs`,
  `top_logprobs`, and `return_token_ids`. Never request token metadata in this
  workflow; RAM issue `#279` records a Kimi Rust-frontend crash
  (`token_ranks must be >=1`) on such requests.
- Every new run snapshots its source config, task list, and image manifest and
  writes SHA-256 provenance under `OUTPUT_DIR/inputs/`.
- `run_eval.sbatch` and `run_oracle.sbatch` are CPU-only controllers with
  8-CPU/16-GiB defaults; VMVM sandboxes and inference capacity are remote.
- `audit_traces.py` fails closed on rollout errors, duplicate/missing tasks,
  missing sampled responses or reasoning, invalid provider usage, malformed
  parent graphs, and provider-reported sequences over 262,144 tokens. Exact
  token-array validation remains available only via `--require-token-data`.

Validated artifacts on the shared checkpoint:

- Mobius oracle, job `1725524`: 2,538 completed, 2,523 valid, 14 invalid,
  1 error (99.408983%).
- TB4 oracle, job `1725604`: 66 completed, 63 valid, 3 explicitly unsupported
  GPU tasks (100% of the CPU-supported subset).
- Exact production manifest:
  `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_full/valid_tasks_2500.txt`;
  2,500 unique tasks; SHA-256
  `d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b`.
- Historical sticky-proxy token smoke, job `1730918`:
  `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/kimi_token_smoke_sticky_v1/results.jsonl`;
  2/2 clean traces, 7,217 sampled tokens, 16/16 sampled nodes retained
  reasoning, response content/tool calls were retained, and strict audit
  passed. The job used 8 CPUs and peaked at about 1.03 GiB RSS. It predates RAM
  issue `#279`, requested now-forbidden logprobs, and is not the readiness gate
  for the replacement deployment.

No full 66-task model eval has completed successfully. The last attempt,
job `1728404`, was canceled after writing 52 unique rows; 42 rows contained
errors, dominated by 252 upstream 502 messages from the old two-replica team
endpoint. Treat `tb4_kimi_k3_max_v1` through `v7` as diagnostic artifacts and
start one fresh run. Do not resume `v7`.

## Current Kimi deployment

RAM source is `/storage/home/tianhaowu/ram_common` at `95dbabedfa77`. The active
deployment is `tianhaowu-k3-tb16-normal-20260915` on `fair-cw-use2-3`:

- requested lifetime: 7 days;
- target: 24 endpoints;
- CPU-only coordinator; each endpoint uses four GB300/g3 nodes, 16 GPUs total,
  tensor parallel 16, and GPU `QOS=normal`;
- Kimi-K3, 1,048,576-token model limit, prefix caching enabled;
- LiteLLM sticky routing enabled with a 43,200-second TTL.

This deployment snapshot still names the vulnerable July 27 stock Kimi image.
RAM issue `#279` proves that omitting logprobs prevents the Rust dispatcher
outage but does **not** prevent silent KDA state-reuse corruption. Before using
the pool, deploy a preview-compatible port of vLLM PR `#51483` and select
`PIECEWISE` CUDA graphs (or eager mode), then semantically soak every route.
The current PR head targets newer vLLM; the compatible preview overlay must be
verified against the pinned image rather than copied blindly. The known
preview-compatible KDA change is vLLM commit
`9ddef960045d20cf83d2eefe5561fa9a56373d11`; pin and validate the derived image
digest rather than a moving tag. `/health` alone is not a correctness signal.

Coordinator job `1731223` is running on `cpu_x86`; endpoint jobs `1731225`-
`1731240` and `1731470`-`1731477` request `g3`/`QOS=normal`. At 2026-09-16
01:49 UTC all 24 endpoint jobs were pending for scheduler priority with no
estimated start time, so the
deployment had zero ready routes and no `proxy_info.json`. Do not submit an
eval until at least 16 routes are healthy, zero are unhealthy, the state is
stable across repeated checks, and the proxy metadata exists. The prior
`g3_lowest` deployment was stopped and archived.

Inspect it without exposing credentials:

```bash
cd /storage/home/tianhaowu/ram_common/vllm_tools/serve_api_v2
./serve.sh status tianhaowu-k3-tb16-normal-20260915 --json | jq \
  '{phase,endpoints_summary,proxy:{url:.proxy.url,state:.proxy.slurm_state,extras:.proxy.extras}}'
```

Proxy metadata (including the secret key) lives at:

```text
/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb16-normal-20260915/proxy_info.json
```

Do not print or commit `api_key`. Before any eval, require the patched runtime,
authenticate to `/health`, and require at least 16 healthy routes with zero
unhealthy routes. Then send repeated semantic completions through every route,
including mixed short/long state-reuse traffic. Use the same
`X-LiteLLM-Session-ID` repeatedly and confirm
that response header `x-litellm-model-api-base` remains identical. Several
different session IDs should span multiple API bases once multiple workers are
healthy. The probe must not request logprobs. Finally run the two-task
transcript smoke and its default audit.

Use the checked-in snapshot/affinity gate after the patched deployment reaches
its intended 24 routes:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/probe_inference_routes.py \
  --proxy-info /checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb16-normal-20260915/proxy_info.json \
  --model Kimi-K3 --expected-routes 24 --requests 192 --repeats 3 \
  --concurrency 32 --health-timeout 30 --timeout 300 --max-tokens 4096 \
  --require-reasoning --pretty
```

It requires model-specific health counts before and after, exactly 24 observed
API bases, published sticky/Redis metadata, zero hidden LiteLLM retries, exact
semantic replies, and sequential same-session backend affinity. This is a
corruption snapshot, not a deterministic reproduction of the one-token KDA
trigger, so it never replaces the patched-image and piecewise/eager gates.

The other-cluster proxy `http://cpu-128-141:8100` is not reachable from this
cluster either directly or through `fwdproxy`. URL-only client pooling was
therefore not committed: direct proxies can also have different credentials.
Combining pools needs a reachable shared gateway or an endpoint structure that
binds each URL to its own key and headers.

## Readiness smoke

All Slurm mutations must be typed through `swebench_vmvm:Launcher.0`.

Run this fresh two-task smoke after the replacement deployment passes its route
health and affinity checks. The job loads the proxy URL and key inside the
compute allocation; the key is not placed in the command or provenance file.

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /storage/home/tianhaowu/prime-rl && env EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_token_smoke.toml INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb16-normal-20260915/proxy_info.json OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/kimi_transcript_smoke_sticky_v2 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

After it finishes:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/audit_traces.py \
  /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/kimi_transcript_smoke_sticky_v2/results.jsonl \
  --expected-count 2 --require-reasoning
```

The gate is exactly 2 traces, zero trace/global problems, nonempty retained
response content/tool calls and reasoning on every sampled node, valid provider
usage, and no provider-reported sequence over 262,144 tokens. Also inspect
`provenance.txt` and `inputs/manifest.json`.

## Launch the requested single full TB4 eval

Only one pass@1 run is requested. Use a new output directory:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /storage/home/tianhaowu/prime-rl && env EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_max_miniswe.toml INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb16-normal-20260915/proxy_info.json OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_full_v2 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

Record the returned job ID. Monitor without mutating the run:

```bash
squeue -j JOB_ID -o '%.18i %.10T %.12M %.24R'
tail -n 100 /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/eval_JOB_ID.log
wc -l /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_full_v2/results.jsonl
```

Expected completion is 66 durable rows and 66 unique task slugs. Report the
63-task CPU-supported score separately from the three explicit GPU-unsupported
tasks. Investigate any provider or VMVM infrastructure error; do not silently
turn it into reward zero. If interrupted, resume the same snapshot with
`RESUME_DIR=.../tb4_kimi_k3_sticky_full_v2` rather than starting a second full
run.

Only after the full TB4 run and trace checks are clean should the 2,500-task
Mobius production run be launched with
`configs/eval/mobius_kimi_k3_max_2500.toml` and the pinned manifest above. Its
fresh output directory is
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/mobius_kimi_k3_max_2500_transcript_v1`;
use the same active deployment's `INFERENCE_PROXY_INFO` path.
