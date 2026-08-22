# SWE benchmarks on VMVM

This directory contains the VMVM-only implementation for SWE-bench Verified and
SWE-rebench. It composes the existing Verifiers v1 runtime without modifying
Verifiers or `vmvm_tb_v2`.

## Supported evaluations

| Benchmark | Harness | Model | Workload |
| --- | --- | --- | ---: |
| SWE-bench Verified | mini-swe-agent 2.2.8 | Nemotron 3 Super | 500 x 1 |
| SWE-bench Verified | OpenHands SDK 1.17.0 | Nemotron 3 Super | 500 x 1 |
| SWE-rebench July 2026 | behavior-compatible text-command ReAct | Qwen3.6-27B | 111 x 5 |
| SWE-rebench July 2026 | mini-swe-agent 2.2.8 native tools | Qwen3.6-27B | 111 x 5 |

Only production configurations are checked in:

```text
configs/
├── eval/
│   ├── swebench_verified_miniswe.toml
│   ├── swebench_verified_openhands.toml
│   ├── swe_rebench_qwen36_react.toml
│   └── swe_rebench_qwen36_miniswe.toml
└── inference/
    ├── nemotron_h100.toml
    ├── nemotron_h200.toml
    ├── qwen36_h100.toml
    └── qwen36_h200.toml
```

Use CLI overrides for smoke runs instead of adding one-off TOMLs.

## Setup

Build the pinned OpenHands SDK environment once:

```bash
sbatch user/tianhaowu/swebench_vmvm/setup_openhands_sdk.sbatch
```

Download the pinned SWE-rebench Harbor dataset once:

```bash
sbatch user/tianhaowu/swebench_vmvm/download_swe_rebench_harbor.sbatch
```

Run one oracle task before a full evaluation:

```bash
sbatch --export=ALL,NUM_TASKS=1 \
  user/tianhaowu/swebench_vmvm/validate_swebench_verified.sbatch

sbatch --export=ALL,NUM_TASKS=1 \
  user/tianhaowu/swebench_vmvm/validate_swe_rebench.sbatch
```

Both validators accept `TASKS` for an exact task and `VMVM_LEASE_TTL` for a
longer lease.

## Start inference

Nemotron Super and Qwen3.6-27B each have H100 and H200 launchers:

```bash
sbatch user/tianhaowu/swebench_vmvm/run_nemotron_inference_h100.sbatch
sbatch user/tianhaowu/swebench_vmvm/run_nemotron_inference_h200.sbatch

sbatch user/tianhaowu/swebench_vmvm/run_qwen36_inference_h100.sbatch
sbatch user/tianhaowu/swebench_vmvm/run_qwen36_inference_h200.sbatch
```

The Nemotron configs retain the `qwen3_coder` tool parser, `nemotron_v3`
reasoning parser, and 262,144-token context. The Qwen configs retain the
`qwen3_coder` tool parser, `qwen3` reasoning parser, and 131,072-token context,
so the same endpoint supports both the ReAct and native-tool evaluations.

Verifiers sends the rollout trace ID as `X-Session-ID` on every model request,
including streamed SDK requests. If an endpoint fronts multiple engines, its
router must consistently hash this header so all turns from one rollout reuse
the same prefix cache. The checked-in inference configs each serve one tensor-
parallel engine, so the header preserves the routing contract without changing
engine selection.

Wait for `/v1/models` to advertise the exact configured model before launching
an evaluator. Use `--no-requeue` for inference jobs; if an endpoint moves, stop
the evaluator and resume its durable output directory against the new endpoint.

## Launch evaluations

Evaluation drivers run on the CPU partition and connect to a separate inference
job:

```bash
sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,\
EVAL_CONFIG=user/tianhaowu/swebench_vmvm/configs/eval/swebench_verified_miniswe.toml \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch

sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,\
EVAL_CONFIG=user/tianhaowu/swebench_vmvm/configs/eval/swebench_verified_openhands.toml \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch

sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,\
EVAL_CONFIG=user/tianhaowu/swebench_vmvm/configs/eval/swe_rebench_qwen36_react.toml \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch

sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,\
EVAL_CONFIG=user/tianhaowu/swebench_vmvm/configs/eval/swe_rebench_qwen36_miniswe.toml \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
```

When the CPU queue is unavailable and the researcher explicitly permits it,
the same launcher may run as an overlapping Slurm step on the exclusive
inference allocation with `CUDA_VISIBLE_DEVICES=`. Keep exactly one evaluator
writer for the result directory; no separate colocated config is needed.

For a smoke run, pass CLI overrides after the launcher:

```bash
sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,EVAL_CONFIG=CONFIG \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch \
  --num-tasks 1 --num-rollouts 1 --max-concurrent 1 --multiplex 1
```

When overriding a plugin-specific field such as `taskset.tasks` alongside an
`@` config, repeat both plugin IDs so the CLI narrows their config types before
parsing the override:

```bash
--taskset.id swe-rebench-harbor --harness.id swe-rebench-react \
  --taskset.tasks TASK_DIRECTORY_NAME
```

The launcher accepts `INFERENCE_BASE_URL` instead of `INFERENCE_JOB_ID`, and
`OUTPUT_DIR` to select a new result directory. It takes an exclusive writer lock
and refuses to truncate an existing result.

Resume an interrupted run only after confirming no evaluator still owns the
directory:

```bash
sbatch --export=ALL,INFERENCE_BASE_URL=http://HOST:8000/v1,\
EVAL_CONFIG=CONFIG,RESUME_DIR=/checkpoint/ram/tianhaowu/swebench_vmvm/evals/run_JOB_ID \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
```

## Harness contracts

`swebench_verified_vmvm/` evaluates each candidate patch in a fresh VMVM
container at the task's base commit. Candidate patch hashes, parsed test reports,
and distinct verifier-runtime descriptors are saved in every result row.
Transient verifier-runtime failures retry only the fresh verifier with the exact
captured patch; they never resample the model trajectory. Whole-rollout retries
are restricted to sandbox or interception-tunnel loss. Model-provider retries
remain inside the individual model request.

`openhands_sdk_harness/` implements NVIDIA's published OpenHands SDK 1.17.0
recipe with Terminal, FileEditor, and TaskTracker, 200 iterations, the published
prompts, and cross-turn reasoning replay.

`swe_rebench_harbor/` adapts the pinned
`ibragim-badertdinov/swe-rebench-07-2026@2026-07` Harbor tasks to Verifiers. The
folder-local `swebench_vmvm_compat.py` handles Python-free VMVM images and Java
proxy trust without changing the shared backend. It captures the exact candidate
patch before scoring. Each Harbor verifier command retains its official
3,000-second limit and records a timeout as a terminal zero score; the larger
outer scoring window exists only so infrastructure retries can finish. If the
agent runtime is lost during scoring, the adapter applies that same captured
patch to a fresh VMVM verifier instead of resampling the model.

`swe_rebench_react/` is a behavior-compatible implementation of the fixed
text-command scaffold described by the Qwen3.6 report. The public benchmark does
not publish the executable internal agent. Its system prompt is checked by hash
during audit. The MiniSWE comparison uses Verifiers' built-in mini-swe-agent
harness with native `bash` tool calls.

## Audit results

Audit the common result shape first:

```bash
uv run --no-sync python user/tianhaowu/swebench_vmvm/audit_results.py \
  RESULTS --expected-tasks 500 --rollouts-per-task 1 \
  --require-swebench-vmvm-provenance --reject-mode-changes --strict
```

Use one rollout per task for both SWE-bench Verified harnesses. For SWE-rebench
use `--expected-tasks 111 --rollouts-per-task 5` and omit the SWE-bench
provenance flags.

Run the harness-specific audit as well:

```bash
uv run --no-sync python user/tianhaowu/swebench_vmvm/openhands_sdk_harness/audit.py \
  RESULTS --expected-rows 500 --strict

uv run --no-sync python user/tianhaowu/swebench_vmvm/swe_rebench_react/audit.py \
  RESULTS --expected-rows 555 --strict

uv run --no-sync python user/tianhaowu/swebench_vmvm/audit_miniswe_native_tools.py \
  RESULTS --strict

uv run --no-sync python user/tianhaowu/swebench_vmvm/swe_rebench_harbor/audit.py \
  RESULTS --require-verifier-metadata --strict
```

For a completed OpenHands 500 x 1 run, preserve the inference config, launcher,
startup log, Slurm job ID, and their checksum manifest in the result directory,
then run the fail-closed finalizer:

```bash
BASE_RESULTS_DIR=/path/to/run \
  bash user/tianhaowu/swebench_vmvm/finalize_openhands_sdk.sh
```

`watch_finalize_openhands_sdk.sh` may wait on an exact evaluator step. It accepts
only a `COMPLETED`/`0:0` step with exactly 500 rows before invoking the finalizer.
The SDK audit accepts `ConversationExecutionStatus.ERROR` only when the agent
cleanly exhausts all 200 model requests, or when Verifiers deliberately ends a
request at the model context limit. The latter must be exactly one terminal HTTP
400 whose agent exception ends with `rollout stopped: context_length`. Any other
SDK error status, agent exception, HTTP error, or transport error fails strict
audit.

If a completed OpenHands row contains a non-context provider or transport error,
run that exact task once with the production config in a separate output
directory. After the 500-task evaluator is terminal, create a new standalone
result directory without editing either source result:

```bash
uv run --no-sync python \
  user/tianhaowu/swebench_vmvm/recover_openhands_infrastructure.py \
  BASE_RESULTS_DIR --replacement-dir CLEAN_ONE_TASK_DIR \
  --output-dir RECOVERED_RESULTS_DIR
```

The recovery command refuses active writer locks and overwrites, requires a
clean replacement with matching task, config, model, official-recipe, archive,
prompt, and runtime-source provenance, restores the task's original dataset
index, and records source/result checksums. Run the normal finalizer on the
recovered directory; it includes the recovery manifest and copied replacement
artifacts in `final.sha256`.

## Result interpretation

SWE-bench Verified reports resolved tasks divided by 500. SWE-rebench reports
resolved rollouts divided by 555; empirical pass@5 is reported separately.
Infrastructure errors, duplicate traces, duplicate verifier runtimes, malformed
provenance, and incomplete rows must all be zero before comparing a score with a
published target.

An older run may contain a `TasksetError: scoring timed out` row because its
outer Verifiers timeout fired at the same instant as the Harbor verifier budget.
After the evaluator is terminal, normalize that exact outcome without resampling
the model:

```bash
uv run --no-sync python \
  user/tianhaowu/swebench_vmvm/recover_swe_rebench_timeouts.py \
  RESULTS --output RECOVERED_RESULTS
```

The recovery tool refuses to run while the result directory's writer lock is
held, accepts only the exact timeout error shape where the old outer timeout
equals the task's official verifier budget, recovers the candidate patch from
the persisted trajectory, and records source/result hashes in its report.
