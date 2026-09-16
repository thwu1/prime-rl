# VMVM sandbox coordination

Last updated: 2026-09-16 00:24 UTC

## First message to the next teammate

Please pull `origin/vmvm-sandbox` and read this file before changing anything.
We are operating on different clusters, so include your cluster in every claim
and do not assume that another owner's Slurm IDs, `cpu-*` URLs, or checkpoint
paths are reachable. I own the `fair-cw-use2-3` Kimi deployment and TB4/Mobius
evaluation orchestration. Do not duplicate the same code fixes or benchmark
run on your cluster without recording why here. Add your name, cluster, scope,
files, and job IDs under **Active claims**, commit that claim, and push it
before editing. I will fetch/rebase before every push and will not force-push
this shared branch again.

## Coordination protocol

1. `git fetch origin && git rebase origin/vmvm-sandbox` before starting work.
2. Add or update one row in **Active claims**, including the cluster, commit
   it, and push normally.
3. Do not edit files or mutate jobs owned by another active row without first
   recording the handoff here.
4. Record each submitted Slurm job, output directory, and terminal result.
5. Before pushing code, fetch/rebase again and run the relevant tests.
6. Never commit API keys. Never force-push this shared branch.
7. On completion, move the row to **Completed work** with evidence and commit.

## Active claims

| Owner | Cluster | Scope | Files | Live resources | State / next gate |
|---|---|---|---|---|---|
| Codex session for `tianhaowu` | `fair-cw-use2-3` | Kimi serving; TB4 pass@1; 2,500-trace launch | `user/tianhaowu/terminal_bench_vmvm/**`, `environments/vmvm_tb_v2/**`, `deps/verifiers` gitlink | deployment `tianhaowu-k3-tb16-normal-20260915` (desired 24); coordinator `1731223`; workers `1731225`-`1731240`, `1731470`-`1731477` | All 24 workers are `g3`/`QOS=normal`, currently pending for priority. The old `g3_lowest` deployment was stopped and archived. Wait for at least 16 healthy/0 unhealthy normal-QoS routes and a stable interval, then launch exactly one fresh full TB4 run; retain the remaining workers toward 24-way trace capacity. |
| Codex session for `tianhaowu` (use2-1) | `fair-cw-use2-1` | Shared-endpoint compatibility and complete model-visible trace audit; Mobius archive staging; no duplicate full eval launch | `configs/eval/tb4_kimi_token_smoke.toml`, `configs/eval/tb4_kimi_k3_max_miniswe.toml`, `configs/eval/mobius_kimi_k3_max_2500.toml`, `COORDINATION.md` | shared deployment `shared-kimi-k3-16w`; terminal diagnostics `1430087`, `1430091`, `1430101`, `1430136`, `1430367` | Disable unneeded logprobs, then prove reasoning, assistant content/tool calls, and tool results survive the trace path; report evidence to the use2-3 owner. |

Add new rows below this line; do not overwrite another owner's row.

## Live evaluation state

- Sticky/token smoke job `1730918` completed: 2/2 traces, 7,217 sampled
  tokens, response/tool calls and reasoning retained, zero audit failures.
- A 64-request inference probe completed 64/64 in 1.21 seconds across all 12
  routes then available. Same-session requests stayed pinned to one route.
- Full TB4 job `1731157` was canceled after 2m54s with no result rows because
  endpoint churn exposed one stale unhealthy route and caused four provider
  500s. It is diagnostic only. The next full output directory must be
  `tb4_kimi_k3_sticky_full_v2`.
- Repaired Mobius corpus is a clean detached worktree at
  `/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/mobius-ac1f30b9`,
  commit `ac1f30b9a`, with 2,538 tasks and all 2,500 selected slugs.
- Repaired-fixture oracle job `1731198` completed with 41/42 valid; CPU-only
  retry `1731363` reran the sole transient timeout with doubled timeout and
  resources. The preserved 42-task summary is now 42/42 valid (100%).
- Replacement Kimi deployment `tianhaowu-k3-tb16-normal-20260915` has a
  CPU-only coordinator (`1731223`) and 24 endpoint jobs (`1731225`-`1731240`,
  `1731470`-`1731477`), all verified by Slurm as `partition=g3`, `qos=normal`,
  16 GPUs per endpoint (384 GPUs total when fully ready).
  The older `g3_lowest` deployment was stopped and archived at 00:03 UTC; its
  remaining workers were canceled and are releasing their nodes.

## Completed work

| Owner | Result | Evidence |
|---|---|---|
| Codex session for `tianhaowu` | VMVM adapter, transport hardening, Compose support, durable eval snapshots/resume, Kimi token/reasoning capture, LiteLLM session affinity | See `HANDOFF.md`; pipeline tests 16/16 and focused verifier tests 30/30 passed. |
| Codex session for `tianhaowu` | Mobius oracle exceeded 90% | Job `1725524`: 2,523/2,538 valid (99.408983%). |
| Codex session for `tianhaowu` | All 42 repaired Mobius fixtures revalidated | Jobs `1731198` and `1731363`: final preserved summary 42/42 valid (100%). |
| Codex session for `tianhaowu` | TB4 oracle validation | Job `1725604`: 63 CPU-supported valid and 3 explicit GPU-unsupported tasks. |

## Known non-overlap boundaries

- The direct proxy `cpu-128-141:8100` is on another cluster and is unreachable
  here. Do not add URL-only pooling; per-endpoint credentials must remain bound
  to their URL/headers.
- Slurm job IDs and `cpu-*` URLs in this file are meaningful only on the
  cluster named in the owning row. Use Git commits in this file—not shared
  scheduler visibility—as the cross-cluster source of truth.
- `tb_tasks.zip` stays on `vmvm-sandbox`, but expanded tasks must not be added
  back to this branch. Use the detached `ac1f30b9a` worktree for Mobius.
- The live RAM `proxy_info.json` contains a secret. Read it through
  `INFERENCE_PROXY_INFO`; never print or commit its `api_key`.
