# Tau3 Banking on VMVM

This folder is a standalone, resumable evaluator for the 97-task Tau3
`banking_knowledge` benchmark. It runs every conversation inside VMVM and uses
the official Tau2 v1.0.1 grading implementation pinned at commit `fc0055d`.

The completed Nemotron 3 Super reproduction scored 57/485 (11.7526%). See
[`RESULTS.md`](RESULTS.md) for the exact protocol, audit, and artifact hashes.

The default parity configuration uses:

- `bm25_grep` retrieval;
- five trials per task with Tau's seed schedule starting at 300;
- Nemotron 3 Super as the policy, with thinking enabled, temperature 1.0, and
  top-p 0.95;
- Kimi K2.6 as the user simulator, non-thinking, with an 8,192-token cap;
- Kimi K2.6 in thinking mode as the NL-assertion judge (only `task_102`
  needs that judge);
- up to five attempts for an empty agent response and 30 for an empty user
  response, matching the NVIDIA Tau3 integration
  (`60c2a0dbf974ea7533456a4706f837c3a6d14afc`); an agent response that
  exhausted its output budget is not retried;
- 200 Tau steps and 10 tool errors per trial.

## Sticky routing

The policy route sends `x-session-id`, which is the header consumed by
prime-rl's `consistent_hash` vLLM router. The Kimi user and judge routes send
`x-litellm-session-id`, which is the shared LiteLLM service's affinity header.
Each value is stable for one task, trial, attempt, and role:
`tau3-{task_id}.{trial}-{attempt}-{role}`.

The checked-in single-node policy server has only one model replica, so affinity
does not change its routing. When the policy URL points to a multi-replica
prime-rl router, keep `policy = "consistent_hash"`; the standard launcher
configures that router with `--request-id-headers x-session-id`. Audit
`proxy_requests.jsonl` for the expected header and stable session value, and
audit the router log to confirm each key maps to exactly one backend.

The current public Artificial Analysis snapshot is 50/485, or
`0.103092783505155`, but its current methodology uses GPT-5.4 Mini rather than
the requested Kimi setup. The Kimi-based target is therefore tracked separately
and must be established by the full reproduction run.

The 30-attempt user behavior originates in NVIDIA's stable merge
`befd120003fb55f48b498f6549556dcaf74582d5`; the later `60c2a0d` tree contains
both that behavior and the five-attempt agent retry.

## Tool-schema scope

The pinned v1.0.1 benchmark exposes 16 initial policy tools under `bm25_grep`.
The private `sft_v5.0_full_20260820` training package instead records a later
17-tool lane and adds `get_cash_back_disputes_by_user`. That extra tool occurs
in 62 SFT trajectories, but the 97 official task definitions used by this
evaluator never reference it. Do not treat this v1.0.1 result as an evaluation
of the later `c88e411d` SFT tool-schema lane.

## Files

- `worker.py`: one official Tau simulation and grade, executed in VMVM.
- `harness.py`: VMVM setup, file transfer, exact-once command recovery, and
  result collection.
- `proxy.py`: authenticated host-side routing to policy, user, and judge
  endpoints without copying real credentials into the sandbox.
- `run_eval.py`: task scheduling, infrastructure-only retries, resume, and
  aggregation.
- `nemotron_super_kimi.toml`: full 97 x 5 configuration.
- `nemotron_super_kimi_smoke.toml`: one-trial smoke configuration.

## Run

Start a dedicated policy server:

```bash
inference_job=$(sbatch --parsable user/tianhaowu/tau3_banking_vmvm/run_nemotron_inference_h100.sbatch)
```

After it is healthy, submit a one-task smoke from a CPU node:

```bash
TAU3_CONFIG=user/tianhaowu/tau3_banking_vmvm/nemotron_super_kimi_smoke.toml \
TAU3_OUTPUT_DIR=/checkpoint/ram/tianhaowu/tau3_banking_vmvm/smoke \
TAU3_POLICY_JOB_ID="$inference_job" \
TAU3_LIMIT=1 TAU3_WORKERS=1 \
sbatch user/tianhaowu/tau3_banking_vmvm/run_eval.sbatch
```

Then run the full benchmark:

```bash
TAU3_POLICY_JOB_ID="$inference_job" \
sbatch user/tianhaowu/tau3_banking_vmvm/run_eval.sbatch
```

`results.jsonl` is append-only and uniquely keyed by `(task_id, trial)`. Reusing
the same output directory resumes missing trials. A different semantic config
fingerprint is rejected.

## Retry semantics

A VMVM transport drop is reattached to the same lease/container and the
in-flight command is collected with `recover_last()`; the command is never sent
again. At most five consecutive transport drops are recovered. If the VM or
container is gone, only the unpersisted trial is rerun in a fresh VMVM sandbox.
Provider transport errors, HTTP 429, and HTTP 5xx responses retry first at the
affected model call; if those attempts are exhausted, the trial is scored once
as a terminal model-error zero. LiteLLM's broad retry loop is disabled so
deterministic HTTP 4xx errors are never retried. Empty successful responses are
also retried only at the affected model call; after five empty agent responses
or 30 empty user responses, or immediately after an agent output-length
exhaustion, the model failure is scored as a terminal zero. Model context-window
exhaustion and simulation timeouts are also terminal zeros. Kimi judge output
is normalized from JSON code fences or a prose prefix; an actually malformed
judge response is retried only at the judge call and then stops the run.
Configuration, authentication, task-loading, and grading errors also stop the
run. The audit rejects every whole-trial retry not immediately preceded by a
`vmvm_lost` attempt.

When VMVM replaces its SSH control master, it restores every registered reverse
forward before collecting the surviving in-flight command. Model-call retries
wait up to five minutes for the local proxy health endpoint, which prevents a
recoverable VMVM transport event from being mis-scored as a provider failure.

Audit an output directory with:

```bash
uv run --frozen python user/tianhaowu/tau3_banking_vmvm/audit.py \
  /checkpoint/ram/tianhaowu/tau3_banking_vmvm/nemotron_super_kimi_k26/results.jsonl \
  --expected-total 485
```

The audit auto-loads the run's copied config, metadata, attempt log, and proxy
log. It verifies task/trial coverage, Tau's seed schedule, source and config
fingerprints, binary rewards, request parameters, and the absence of repeated
deterministic provider errors.
