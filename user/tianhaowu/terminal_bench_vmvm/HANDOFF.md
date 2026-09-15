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
revision preserves provider token IDs and log probabilities, makes large evals
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
- Every new run snapshots its source config, task list, and image manifest and
  writes SHA-256 provenance under `OUTPUT_DIR/inputs/`.
- `audit_traces.py` fails closed on rollout errors, duplicate/missing tasks,
  absent token IDs, mask/logprob misalignment, missing reasoning, malformed
  parent graphs, and sequences over 262,144 tokens.

Validated artifacts on the shared checkpoint:

- Mobius oracle, job `1725524`: 2,538 completed, 2,523 valid, 14 invalid,
  1 error (99.408983%).
- TB4 oracle, job `1725604`: 66 completed, 63 valid, 3 explicitly unsupported
  GPU tasks (100% of the CPU-supported subset).
- Exact production manifest:
  `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/mobius_full/valid_tasks_2500.txt`;
  2,500 unique tasks; SHA-256
  `d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b`.
- Successful sticky-proxy token smoke, job `1730918`:
  `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/kimi_token_smoke_sticky_v1/results.jsonl`;
  2/2 clean traces, 7,217 sampled tokens, 16/16 sampled nodes retained
  reasoning, response content/tool calls were retained, and strict audit
  passed. The job used 8 CPUs and peaked at about 1.03 GiB RSS.

No full 66-task model eval has completed successfully. The last attempt,
job `1728404`, was canceled after writing 52 unique rows; 42 rows contained
errors, dominated by 252 upstream 502 messages from the old two-replica team
endpoint. Treat `tb4_kimi_k3_max_v1` through `v7` as diagnostic artifacts and
start one fresh run. Do not resume `v7`.

## Current Kimi deployment

RAM source is `/storage/home/tianhaowu/ram_common` at `95dbabedfa77`. The active
deployment is `tianhaowu-k3-tb24-20260915` on `fair-cw-use2-3`:

- requested lifetime: 7 days;
- target: 24 endpoints;
- each endpoint: four GB300/g3 nodes, 16 GPUs total, tensor parallel 16;
- Kimi-K3, 1,048,576-token model limit, prefix caching enabled;
- LiteLLM sticky routing enabled with a 43,200-second TTL.

The first launch failed because the ARM control-plane environment was absent;
Slurm job `1729335` installed it. A later temporary resize from 24 to 10
canceled the workers that had become ready. The deployment has been restored
to 24. Replacement workers regenerated the proxy successfully; the latest
validated state had 12 healthy routes and no unhealthy routes. Five requests
with one session ID stayed on exactly one backend, while eight distinct IDs
spanned three backends. A 64-way distinct-session burst completed 64/64 in
1.21 seconds across all 12 routes with no errors. Continue checking health
because the remaining endpoints may join later, and never infer readiness only
from the proxy process state.

Inspect it without exposing credentials:

```bash
cd /storage/home/tianhaowu/ram_common/vllm_tools/serve_api_v2
./serve.sh status tianhaowu-k3-tb24-20260915 --json | jq \
  '{phase,endpoints_summary,proxy:{url:.proxy.url,state:.proxy.slurm_state,extras:.proxy.extras}}'
```

Proxy metadata (including the secret key) lives at:

```text
/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb24-20260915/proxy_info.json
```

Do not print or commit `api_key`. Before any eval, authenticate to `/health`
and require `healthy_count > 0`; preferably wait for the intended pool. Then
send repeated tiny completions with the same `X-LiteLLM-Session-ID` and confirm
that response header `x-litellm-model-api-base` remains identical. Several
different session IDs should span multiple API bases once multiple workers are
healthy. Finally run the two-task token smoke and its strict audit.

The other-cluster proxy `http://cpu-128-141:8100` is not reachable from this
cluster either directly or through `fwdproxy`. URL-only client pooling was
therefore not committed: direct proxies can also have different credentials.
Combining pools needs a reachable shared gateway or an endpoint structure that
binds each URL to its own key and headers.

## Readiness smoke

All Slurm mutations must be typed through `swebench_vmvm:Launcher.0`.

The two-task smoke below passed as job `1730918`. Rerun it after changing the
model deployment or transport. The job loads the proxy URL and key inside the
compute allocation; the key is not placed in the command or provenance file.

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /storage/home/tianhaowu/prime-rl && env EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_token_smoke.toml INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb24-20260915/proxy_info.json OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/kimi_token_smoke_sticky_v1 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

After it finishes:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/audit_traces.py \
  /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/kimi_token_smoke_sticky_v1/results.jsonl \
  --expected-count 2 --require-reasoning
```

The observed gate was exactly 2 traces, zero trace/global problems, 7,217
sampled tokens, and retained reasoning. Also inspect `provenance.txt` and
`inputs/manifest.json`.

## Launch the requested single full TB4 eval

Only one pass@1 run is requested. Use a new output directory:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /storage/home/tianhaowu/prime-rl && env INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-tb24-20260915/proxy_info.json OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_full_v1 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

Record the returned job ID. Monitor without mutating the run:

```bash
squeue -j JOB_ID -o '%.18i %.10T %.12M %.24R'
tail -n 100 /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/eval_JOB_ID.log
wc -l /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_full_v1/results.jsonl
```

Expected completion is 66 durable rows and 66 unique task slugs. Report the
63-task CPU-supported score separately from the three explicit GPU-unsupported
tasks. Investigate any provider or VMVM infrastructure error; do not silently
turn it into reward zero. If interrupted, resume the same snapshot with
`RESUME_DIR=.../tb4_kimi_k3_sticky_full_v1` rather than starting a second full
run.

Only after the full TB4 run and trace checks are clean should the 2,500-task
Mobius production run be launched with
`configs/eval/mobius_kimi_k3_max_2500.toml` and the pinned manifest above.
