# RL Orchestrator Silent-Hang — Root Cause & Handoff (2026-06-23)

## TL;DR
12k RL run (`tb_rl_12k_200k_lr1e5_dtype32_rr`, SLURM job 7462180) silently froze at **17:21** after 6 training steps, then SLURM reaped it ~19:46. It is **NOT memory** (1.5 TB free), **NOT the trainer** (clean Step 5 then idle), **NOT primarily threads** (secondary symptom).
**ROOT CAUSE:** at **17:22:00 a host became unreachable**; the verifiers `ZMQEnvServer.send_response` caught the resulting `zmq.ZMQError` ("Host unreachable") and **only logged a WARNING and dropped the completed-rollout response — no retry / reconnect / re-queue / reschedule / fatal.** It dropped **376 results over 2h20m (17:22→19:42), never recovering** → the orchestrator never received completed rollouts → `train_sink`/batch frozen at 179/256 → trainer starved → job reaped.

## Evidence
- `trainer.log`: `16:00:21 SUCCESS Step 5 | 1h44m | Reward 0.43 | Mismatch KL 0.0035`, then idle, no error.
- `orchestrator.log`: last `Train batch 179/256` status line at **17:21:42**, then ZERO more (main loop stopped getting completions). `ROLLOUT_STATE`/`ROLLOUT DONE` beacons CONTINUED to 19:43 (env subprocesses alive, logging independently).
- `logs/envs/train/tb-12k-200k-lr1e5-off1/env_server.log`: `Failed to forward response: Host unreachable` — first **17:22:00**, **376 occurrences**, last 19:42:15.
- Node: 2 TB RAM, 162 G used (8%) → memory ruled out. threads_total peaked 1033, event-loop lag max 11 s → secondary effects of the network failure.

## Root cause (exact code)
`deps/verifiers/verifiers/serve/server/zmq_env_server.py:43-50`
```python
async def send_response(self, client_id, request_id, response_bytes):
    try:
        await self.frontend.send_multipart([client_id, request_id, response_bytes])
    except zmq.ZMQError as e:
        self.logger.warning(f"Failed to forward response: {e}")   # logs + DROPS, no recovery
```
`self.frontend` is a ZMQ **ROUTER** socket with **`ROUTER_MANDATORY=1`** (line 37) → when the client (orchestrator) becomes unroutable, `send_multipart` raises `EHOSTUNREACH`. The handler drops the response. No retry, reconnect, re-queue, reschedule, or fatal escalation → one transient host blip = indefinite silent wedge.

## Fix direction (the missing recovery)
In `send_response` / the router `on_response` path:
1. On `ZMQError`: retry with backoff; if it persists, **re-queue the response / reschedule that rollout** so its group can still finalize.
2. **Detect a persistently-unreachable client and escalate to a FATAL** (crash the job) instead of dropping forever — so SLURM / the monitor relaunches rather than silently freezing.
3. Optional: client heartbeat; on identity loss, force the `ZMQEnvClient` to re-register so the ROUTER can route again.
Goal: turn "one host unreachable → permanent silent freeze" into "degrade or fail-fast".

## Contributing factors (separate issues)
1. **Runaway rollout length**: policy turns grew 44→58→88→101→ individual rollouts at **150-275 turns, 30-60 min each**. Slows batch fill (a group needs all 16) and stresses VMs. Not the freeze cause, but makes it slow (~2h/step) and fragile.
2. **lease_ttl=2400s (40 min) < rollout duration**: VMs can be lost mid-rollout (mass `tar: /tests: Cannot open` at 17:23). `--auto-renew` is set but VMs still dropped.
3. **"Trainer waits hours per step"** = idle waiting for the orchestrator batch, NOT compute (actual step compute is minutes; tokens/s high only during the brief compute burst).

## Current state
- **12k (7462180): DEAD** (reaped). `checkpoints/step_5` exists → resumable: `uv run --no-sync rl @ <cfg> --output-dir /checkpoint/ram/tianhaowu/tb_rl_12k_200k_lr1e5_dtype32_rr/20260623-012555 --resume-step -1` (cancel the dead job first; user previously declined relaunch).
- **17k (7464633): RUNNING, healthy**, 7 steps, nodes h200-005-021,053-[038,098],095-056,114-[098,150]. **SAME vulnerability** — if one of its nodes goes unreachable, expect the identical silent freeze. Watch `Train batch` line going stale while `ROLLOUT DONE` keeps advancing.
- Instrumentation committed **721f678f0** (per-rollout ROLLOUT_STATE beacons +gid, group drop/partial logging, rollout_monitor.py). NCCL-timeout monkeypatch + backend.py docker-auth left UNCOMMITTED. **docker-auth was REVERTED to anonymous pulls** (account 200/6h accumulates; anonymous per-IP bursts but self-recovers).
- **KL mismatch healthy (~0.004)**: router replay ON (config + inference capture confirmed) and **fp32 lm_head ON on both sides** (vLLM `fp32 lm_head ENABLED` + trainer fused chunked head, runtime-verified: outputs fp32 even for bf16 input). NOT the lm_head; residual is bf16-body + CP-attention, within prime-rl's <0.01 target.

## How to detect this hang in monitoring
`orchestrator.log` `Train batch X/256` line goes STALE (timestamp stops) while `ROLLOUT DONE` count keeps rising → grep `logs/envs/*/*/env_server.log` for `Failed to forward response: Host unreachable`. That = this failure mode.
Monitor: `python user/tianhaowu/fair-sc-3/scripts/rollout_monitor.py --groups N`

## Recv side is the OTHER half (added)
The orchestrator's ZMQEnvClient awaits each rollout response with NO timeout:
- env_client.py:63,104 -> handle_run_rollout_request(request, timeout=None)
- zmq_env_client.py:84-86 -> send_request(request, RunRolloutResponse, timeout=timeout) with timeout=None
So when the server drops the response (Host unreachable), the client AWAITS FOREVER -> orchestrator rollout coroutines hang -> batch frozen. Both halves lack recovery: server drops (no retry/reschedule), client waits eternally (timeout=None). recovery_timeout=600s exists but is NOT applied to the in-flight run_rollout await.
FIX (recv side): finite per-request timeout on run_rollout/run_group so a lost response -> timeout -> rollout errors -> group finalizes/reschedules instead of hanging.
