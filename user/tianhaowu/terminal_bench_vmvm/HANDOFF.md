# VMVM Terminal-Bench handoff

State captured on 2026-09-16 UTC. The takeover branch is `vmvm-sandbox`.

## 13:30 UTC replacement update

The vulnerable `tianhaowu-k3-tb24-nocache-20260916` deployment never allocated
an endpoint and was recoverably archived. Its stale route gate was canceled.
The unallocated two-endpoint normal-QoS replacement was also archived after its
workers received September 18 estimates. Active replacement
`tianhaowu-k3-kda-tb1-low-20260916` was submitted from the same exact RAM PR
`#285` source tree (digest-pinned KDA/logprobs fix plus `PIECEWISE` graphs):
coordinator `1735915`, endpoint `1735929`, and readiness gate `1735934`. It is
booting at 0/1 on the approved cluster-default `g3_lowest` QoS, where its
scheduler priority is 100,748 instead of roughly 875. No Kimi task job is
active. First require exact 1/1 route readiness, the semantic/state-reuse probe,
and an approved two-task transcript smoke. The fresh full TB4 config starts at
four active rollouts with two simultaneous VMVM lease starts; do not restore the
old 64/32 model-eval setting.

The Harbor adapter now enforces declared `network_mode = "no-network"` at the
untrusted phase boundary. It retains only a private internal IPv4 network,
preserves Compose aliases, permits the main container's dynamic reverse tunnel,
and rejects external DNS, the injected gateway proxy, and sidecar access to the
tunnel. Canary `1735508` passed all of those checks without task or model data.
The effective corpus policies are 2,538/2,538 shared no-network/no-network for
Mobius, and 64 separate public/public plus two separate public/no-network for
TB4. The first strict repaired-fixture run, `1735580`, finished 22/42 with 20
verifier-invalid results and zero infrastructure failures; its dependent full
job `1735598` was canceled without running. That run combined exact solution
isolation with pre-agent verifier dependency installation, so parent
`f5789724d` removes the latter as a confounder: it builds all verifier wheels
without installing them, stores the wheelhouse on controller disk, and
re-probes/installs offline only after the isolated agent/solution. Strict
42-task rerun `1735716` finished 21/42 valid and 21/42 invalid with zero
infrastructure errors. This isolates the remaining incompatibility to trusted
legacy `solve.sh` scripts that download dependencies under their declared agent
`no-network` policy. Full strict job `1735733` was canceled without running.
Production rollouts remain strictly isolated. Corpus qualification uses an explicit,
provenance-labeled `ORACLE_SOLUTION_NETWORK_MODE=public` compatibility lane:
only trusted image startup and the reference solution retain setup egress, and
the declared policy activates before artifact collection or verification.
Compatibility repair gate `1735886` finished 37/42 valid with five
declared-offline verifier failures and zero infrastructure failures. Clean full job
`1735924` is running all 2,538 tasks at 64 active/32 simultaneous starts; it
must exceed 90% and leave at least 2,500 valid tasks. Report the strict and
compatibility semantics separately.

The cached-wheel implementation is fail-closed: trusted prefetch uses
`--only-binary=:all:` so it cannot execute sdist build hooks; all shared
verifier-no-network tasks prefetch before the agent even when the agent is
public; and hidden tests are not staged until the verifier boundary. Controller
archives are mode 0400, hash-checked, bounded by exact compatibility keys, and
owned by a taskset-lifetime `TemporaryDirectory` without a bound `atexit`
reference; sandbox copies are removed in `finally` paths.

## Start here

```bash
cd /storage/home/tianhaowu/prime-rl
git fetch origin
git switch vmvm-sandbox
git pull --ff-only origin vmvm-sandbox
git submodule update --init --recursive
```

The parent repository pins `deps/verifiers` at `15e22ca5`. That verifier
revision preserves assistant responses, reasoning, tool transcripts, and the
exact parsed provider request/response JSON (streaming responses are a
normalized aggregate, not raw SSE frames). It also makes large evals durable,
retries transient VMVM setup failures, and sends both `X-Session-ID` and the
LiteLLM-consumed `X-LiteLLM-Session-ID` from a stable rollout ID. When token IDs
are intentionally absent, it uses provider-reported usage as the conservative
best-known size for the next turn's token budget and retains the post-response
256K hard guard. Exact token arrays remain authoritative whenever present.

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
- The 66-task Kimi config is pass@1, max reasoning, eight rollout/HTTP concurrency,
  200 turns, and a 262,144-token total cap. Eleven Compose tasks use the real
  multi-service path. Three GPU tasks are explicitly unsupported by the
  current CPU-only VMVM tenant, leaving 63 CPU-supported tasks.
- All five model-eval configs omit `logprobs`, `prompt_logprobs`,
  `top_logprobs`, and `return_token_ids`. RAM issue `#279` records a Kimi
  Rust-frontend crash (`token_ranks must be >=1`) specifically when logprobs
  are requested. Completion IDs are omitted separately because the user only
  needs response and reasoning transcripts.
- All five configs enable compact, hash-checked model-I/O capture and apply the
  four-field denylist after every sampling/dialect override. The default trace
  audit reconstructs request deltas, verifies every request/response hash,
  requires tool schemas, and fails if a forbidden field survived.
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
- Exact production manifest, committed as an opaque cross-cluster artifact:
  `configs/eval/mobius_valid_tasks_2500.txt`; 49,334 bytes, 2,500 lines;
  SHA-256
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

## Kimi deployment state

RAM PR `#285` pins the ARM64 Kimi image by digest and couples the KDA metadata
fix to `PIECEWISE` CUDA graphs. Its PR-head tree is
`b7da70d77604d00cd89578b9bcfb5183eed6814e`; the local deployment checkout at
`a3f5baf` has that exact tree. Active deployment
`tianhaowu-k3-kda-tb1-low-20260916` on `fair-cw-use2-3` requests:

- seven days of serving lifetime and a 7,200-second startup grace;
- one endpoint for the TB4 qualification stage;
- four GB300/g3 nodes and 16 GPUs per endpoint, tensor parallel 16,
  `g3_lowest` QoS;
- the digest-pinned patched image, 1,048,576-token model limit, and
  `PIECEWISE` graphs;
- LiteLLM sticky routing and prefix caching enabled.

Coordinator `1735915` is running; endpoint job `1735929` is pending for
priority with a current September 18 08:55 UTC estimate, so no proxy exists yet.
Shorter-walltime scheduler probes did not improve that estimate; keep seven
days to avoid an unsafe one-route rollover during TB4. The older vulnerable
deployment remained
0/24 and was archived at 10:58 UTC without ever allocating a worker; the
unallocated two-endpoint normal-QoS deployment was archived at 13:28 UTC.
Gate `1735934` waits for exact 1/1 readiness and then owns the per-route
semantic, affinity, and one-token state-reuse probe. Do not submit task jobs
before it exits successfully.

Inspect it without exposing credentials:

```bash
cd /storage/home/tianhaowu/ram_common_pr285/vllm_tools/serve_api_v2
./serve.sh status tianhaowu-k3-kda-tb1-low-20260916 --json | jq \
  '{phase,endpoints_summary,proxy:{url:.proxy.url,state:.proxy.slurm_state,extras:.proxy.extras}}'
```

Proxy metadata (including the secret key) lives at:

```text
/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/proxy_info.json
```

Do not print or commit `api_key`. Before any eval, verify the frozen patched
settings, authenticate to `/health`, and require exactly one healthy route with
zero unhealthy routes. Then send repeated semantic completions through every route,
including mixed short/long state-reuse traffic. Use the same
`X-LiteLLM-Session-ID` repeatedly and confirm
that response header `x-litellm-model-api-base` remains identical. Different
session IDs must remain on that one advertised API base. The probe must not
request logprobs. Finally run the two-task
transcript smoke and its default audit.

Use the checked-in snapshot/affinity gate after the deployment reaches its
intended route:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/probe_inference_routes.py \
  --proxy-info /checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/proxy_info.json \
  --model Kimi-K3 --expected-routes 1 --requests 8 --repeats 3 \
  --concurrency 1 --health-timeout 30 --timeout 300 --max-tokens 4096 \
  --require-reasoning --pretty
```

It requires model-specific health counts before and after, exactly 24 API-base
observations, published sticky/Redis metadata, zero hidden LiteLLM retries, exact
semantic replies, and sequential same-session backend affinity. This is a
corruption snapshot, not a deterministic reproduction of the one-token KDA
trigger, so it never replaces the isolation/configuration checks or close
monitoring during the smoke and full run.

The other-cluster proxy `http://cpu-128-141:8100` is not reachable from this
cluster either directly or through `fwdproxy`. URL-only client pooling was
therefore not committed: direct proxies can also have different credentials.
Combining pools needs a reachable shared gateway or an endpoint structure that
binds each URL to its own key and headers.

## Readiness smoke

All Slurm mutations must be typed through `swebench_vmvm:Launcher.0`.

The active readiness job is:

```text
1735934 readiness and semantic/state-reuse gate
```

Gate artifact:
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/gates/k3_kda_tb1_low_readiness_v1.json`.
No smoke or full eval is dependency-submitted yet; create them only from a
tested commit after this gate succeeds.

Gate `1735392` failed safely in two seconds with `serve_sh_unavailable` because
its launcher path named the deployment's Python package snapshot instead of an
executable checkout. Gate `1735410` then exposed that the PR checkout's local
virtualenv was ARM-only on the x86 controller and was canceled before reaching
its failure threshold. Both sent no model traffic and created no eval output;
`1735467` was canceled when its unallocated normal-QoS deployment was archived.
Replacement `1735934` uses the x86-compatible main status client against the
one-endpoint patched deployment and pins spec SHA-256
`a296613aea26c4401385f70e16c81bc363f670203a5b29b7e1eec3bcef086ccf`.

Monitor the active chain with:

```bash
squeue -j 1735934 \
  -o '%.18i %.28j %.10T %.10M %.50R'
tail -n 50 /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/route_gate_1735934.log
```

Run this fresh two-task smoke after the replacement deployment passes its route
health and affinity checks. The job loads the proxy URL and key inside the
compute allocation; the key is not placed in the command or provenance file.

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  "cd /storage/home/tianhaowu/prime-rl && env PROJECT_DIR=\$PWD EVAL_EXPECTED_PRIME_RL_REVISION=<commit> EVAL_APPROVED_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_token_smoke.tasks.txt EVAL_APPROVED_TASK_FILE_SHA256=ecdcbc6e4f54b690e64b4566de5eecf33467088c8ca3436738cd7308d4e45b83 EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_approved_smoke.toml INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/proxy_info.json OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/kimi_kda_tb1_low_approved_smoke_v1 VACLI_MAX_CONCURRENT_LEASES=2 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

After it finishes:

```bash
uv run --project user/tianhaowu/terminal_bench_vmvm \
  python user/tianhaowu/terminal_bench_vmvm/audit_traces.py \
  /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/kimi_kda_tb1_low_approved_smoke_v1/results.jsonl \
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
  "cd /storage/home/tianhaowu/prime-rl && env PROJECT_DIR=\$PWD EVAL_EXPECTED_PRIME_RL_REVISION=<commit> EVAL_APPROVED_TASK_FILE=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_qwen_a95b_miniswe.tasks.txt EVAL_APPROVED_TASK_FILE_SHA256=9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892 EVAL_CONFIG=\$PWD/user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_max_miniswe.toml INFERENCE_PROXY_INFO=/checkpoint/ram/shared/vllm_deployments_v2/tianhaowu-k3-kda-tb1-low-20260916/proxy_info.json OUTPUT_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_full_v3 VACLI_MAX_CONCURRENT_LEASES=2 sbatch --parsable user/tianhaowu/terminal_bench_vmvm/run_eval.sbatch" C-m
```

Record the returned job ID. Monitor without mutating the run:

```bash
squeue -j JOB_ID -o '%.18i %.10T %.12M %.24R'
tail -n 100 /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/eval_JOB_ID.log
wc -l /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_full_v3/results.jsonl
```

Expected completion is 66 durable rows and 66 unique task slugs. Report the
63-task CPU-supported score separately from the three explicit GPU-unsupported
tasks. Investigate any provider or VMVM infrastructure error; do not silently
turn it into reward zero. If interrupted, resume the same snapshot with both
`RESUME_DIR=.../tb4_kimi_k3_sticky_full_v3`, the same approved task-file pair,
and the same deployment's
`INFERENCE_PROXY_INFO`; the credential is not stored in the snapshot. Do this
rather than starting a second full run.

After the evaluator finishes, submit a fresh strict audit that enforces exactly
66 unique tasks, 63 supported results plus the three known CPU-only
`UnsupportedTaskError` records, clean reasoning/model-I/O/KDA audits, binary
`rewards.solved`, and a supported-task pass rate in `[0.04, 0.22]`. Do not
launch production merely because the eval job exits zero; require the audit's
`checkpoint.json` to contain `"ok": true`.

The historical direct-worker fallback is pinned in
`configs/eval/tb4_kimi_k3_direct_{a,b}.toml`. It assigns each of the 66 tasks to
exactly one fixed worker, at concurrency four per worker, so a trajectory cannot
move between engines. The corresponding 33-line task manifests have SHA-256
`d0f7c0297a82edf79f3e966ffd830fb418ea90c9faa7c4f3d288d5c7bacd1365`
and `485c1a038efc72a4eddf4928758c74d31827ebb7624108cee63e503df0fa02ec`;
their union is the full TB4 set and their intersection is empty. Both direct
worker ports are currently offline; run these only after replacement workers
pass fresh smokes. Run both only
after separate no-logprob smokes, with `OPENAI_API_KEY=EMPTY` and no proxy
environment. Use `VACLI_MAX_CONCURRENT_LEASES=2` in each submission so the two
controllers create at most four leases at once.

The `_v1` attempt at aggregate concurrency 32 is diagnostic and invalid: jobs
`1733765` and `1733766` produced 19 tunnel-exposure failures and five Compose
failures, with 11 errors among the first 13 rows, then were canceled. Dependent
merge `1733767` was also canceled. Do not resume or merge those directories;
all fresh shard and combined output paths use `_v2`.

Keep the two output directories independently resumable. After both contain
33 rows, run `combine_tb4_shards.py` as documented in the README. It refuses an
active writer, wrong endpoint, invalid input snapshot hashes or provenance,
different code revisions, missing/duplicate tasks or trace IDs, and any failure
from `audit_tb4_results.py`. It records the source artifact hashes and publishes
the combined 66-row directory by one atomic rename; never use the combined
directory as a resume target.

Only after the full TB4 run and trace checks are clean should the 2,500-task
Mobius production run be launched with
`configs/eval/mobius_kimi_k3_max_2500.toml` and the pinned manifest above. Its
fresh output directory is
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/mobius_kimi_k3_max_2500_transcript_v2`;
use the same active deployment's `INFERENCE_PROXY_INFO` path after it has been
resized and requalified. Override the
generic evaluator limit with `sbatch --time=7-00:00:00`; the default two-day
controller allocation is intentionally insufficient as a worst-case bound for
2,500 long rollouts. Task loading now fails before any model call unless the
Mobius worktree is clean at exact commit
`ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366`, the task manifest has SHA-256
`d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b`,
and the image manifest has SHA-256
`118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009`.

Mini-swe-agent owns provider-call retries and is explicitly configured for 10
total attempts. If those are exhausted, TB4 and production retry the complete
rollout up to twice for `ProviderError`, `SandboxError`, `TunnelError`, or the
narrow `InterceptionError`; a new trace/session can escape a transiently bad
sticky backend or interception transport. Do not add broad `HarnessError`
retries: malformed requests and deterministic harness failures must remain
terminal. For a resumed job,
pass both `RESUME_DIR` and the same `INFERENCE_PROXY_INFO`. The saved config
contains the old proxy URL but deliberately no API key, so `RESUME_DIR` alone
would authenticate with the placeholder key. Confirm the original deployment
proxy is still live before resuming; do not silently rebind an old run to a
different proxy.
