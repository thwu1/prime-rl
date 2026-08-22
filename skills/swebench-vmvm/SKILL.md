---
name: swebench-vmvm
description: Launch, monitor, recover, audit, and report SWE-bench Verified and SWE-rebench evaluations on the VMVM backend. Use for the Nemotron MiniSWE or official OpenHands SDK reproductions, Qwen3.6 ReAct or MiniSWE comparisons, H100/H200 inference selection, Harbor dataset setup, result provenance, or benchmark matrix reporting.
---

# SWE benchmarks on VMVM

Keep benchmark implementation and configuration in
`user/tianhaowu/swebench_vmvm/`. Read that directory's `README.md` before
changing or launching the workflow.

Do not patch `deps/verifiers`, `environments/vmvm_tb_v2`, or another shared
runtime to fix a benchmark-specific issue. Implement compatibility locally in
`swebench_vmvm_compat.py` or the benchmark adapter unless the user explicitly
authorizes a shared change.

## Supported matrix

| Benchmark | Harness | Model | Shape |
| --- | --- | --- | ---: |
| SWE-bench Verified | mini-swe-agent 2.2.8 | Nemotron 3 Super | 500 x 1 |
| SWE-bench Verified | OpenHands SDK 1.17.0 | Nemotron 3 Super | 500 x 1 |
| SWE-rebench July 2026 | fixed text-command ReAct | Qwen3.6-27B | 111 x 5 |
| SWE-rebench July 2026 | mini-swe-agent 2.2.8 native tools | Qwen3.6-27B | 111 x 5 |

The ReAct implementation is behavior-compatible with the published Qwen3.6
scaffold. Do not call it vendored official agent code: the public benchmark
does not publish that executable scaffold.

## Keep the tree lean

Treat the four files under `configs/eval/` and four files under
`configs/inference/` as the supported configuration surface. Use CLI overrides
for one-task smoke runs. Do not add result files, generated configs, repair
configs, temporary scripts, or experiment-only harness variants to the repo.

Store evaluation output under `/checkpoint/ram/tianhaowu/swebench_vmvm/`, never
under the source tree.

## Scheduler rule

Run state-changing Slurm commands through tmux pane
`swebench_vmvm:Launcher.0`. This includes `sbatch`, `scancel`, and mutating
`scontrol` commands. Read-only `squeue` and `sacct` checks may run directly.
Treat every `sbatch` command below as a payload to send through that pane.

For example:

```bash
tmux send-keys -t swebench_vmvm:Launcher.0 \
  'sbatch user/tianhaowu/swebench_vmvm/run_nemotron_inference_h100.sbatch' Enter
```

Run evaluators on CPU nodes. Keep model serving in a separate H100 or H200 job.
If the CPU queue is blocked and the user permits colocation, run the evaluator
as a separate overlapping step on the exclusive inference allocation, hide its
GPUs with `CUDA_VISIBLE_DEVICES=`, and retain the one-writer result-directory
invariant. Do not add a one-off colocated launcher to the repository.

## Prepare dependencies

Build the pinned OpenHands SDK runtime once:

```bash
sbatch user/tianhaowu/swebench_vmvm/setup_openhands_sdk.sbatch
```

Download the pinned SWE-rebench Harbor package once:

```bash
sbatch user/tianhaowu/swebench_vmvm/download_swe_rebench_harbor.sbatch
```

Before a full run, execute the matching one-task oracle gate:

```bash
sbatch --export=ALL,NUM_TASKS=1 \
  user/tianhaowu/swebench_vmvm/validate_swebench_verified.sbatch
sbatch --export=ALL,NUM_TASKS=1 \
  user/tianhaowu/swebench_vmvm/validate_swe_rebench.sbatch
```

## Start inference

Select one launcher for the available GPU type:

```bash
sbatch user/tianhaowu/swebench_vmvm/run_nemotron_inference_h100.sbatch
sbatch user/tianhaowu/swebench_vmvm/run_nemotron_inference_h200.sbatch
sbatch user/tianhaowu/swebench_vmvm/run_qwen36_inference_h100.sbatch
sbatch user/tianhaowu/swebench_vmvm/run_qwen36_inference_h200.sbatch
```

Require `/v1/models` to advertise the exact model before starting evaluation.
Use Nemotron's `qwen3_coder` tool parser, `nemotron_v3` reasoning parser, and
262,144-token context. Use Qwen's `qwen3_coder` tool parser, `qwen3` reasoning
parser, and 131,072-token context.

Keep per-rollout session affinity enabled. The pinned Verifiers v1 client sends
`X-Session-ID` with `session.trace.id` on every ordinary or streamed model turn.
That value must remain stable within a rollout and distinct across rollouts. A
multi-engine endpoint must consistently hash this header; the production
single-node tensor-parallel configs have only one engine and need no router.

Do not requeue an inference job while an evaluator retains its node URL. After
an endpoint loss, stop the evaluator, restore a healthy endpoint, then resume
the durable result directory.

## Launch an evaluation

Set `EVAL_CONFIG` to one production config and provide either
`INFERENCE_JOB_ID` or `INFERENCE_BASE_URL`:

```bash
sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,EVAL_CONFIG=CONFIG \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
```

Use a production config with positional CLI overrides for smoke runs:

```bash
sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,EVAL_CONFIG=CONFIG \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch \
  --num-tasks 1 --num-rollouts 1 --max-concurrent 1 --multiplex 1
```

For a plugin-specific override such as `--taskset.tasks`, repeat the taskset and
harness IDs after the `@` config (`--taskset.id ... --harness.id ...`). Without
those IDs, pydantic-config sees only the base plugin types and cannot parse the
task list override.

The launcher owns an exclusive output lock. Never run two writers against the
same result directory. Resume only missing or errored work with `RESUME_DIR`
after proving the prior evaluator is terminal.

Keep model-provider retries inside the individual request. Restrict whole-
rollout retries to `SandboxError` and `TunnelError`. SWE-bench Verified retries
a failed fresh verifier on a new VMVM runtime with the exact captured candidate
patch; it must not resample the model merely because scoring infrastructure
failed.

For SWE-rebench Java tasks, restore the harness-owned Maven and Gradle mirror
files immediately before scoring. Agent commands can modify user-level build
configuration, so setup-time mirror installation alone is not sufficient.

Keep the official 3,000-second SWE-rebench verifier limit inside the remote
shell command. A verifier timeout is a terminal zero-score benchmark outcome,
not an infrastructure error. The eval's outer scoring timeout is 14,400 seconds
only to accommodate up to four network-infrastructure attempts and their
backoff. Capture the exact candidate patch during `finalize` before any verifier
runs. If the agent VM is lost during scoring, retry only the verifier in a fresh
VMVM with that captured patch; never resample the completed model trajectory.

For a historical row where the old outer timeout produced exactly
`TasksetError: scoring timed out`, wait for the evaluator to become terminal and
run `recover_swe_rebench_timeouts.py` into a new result file. It refuses the
active writer lock, requires the old outer timeout to equal the task's official
verifier budget, rejects any other error shape, reconstructs the last exact
`git diff` from the saved trajectory, and assigns the official timeout score of
zero without issuing another model request.

## Audit results

Use `audit_results.py` for row shape, task multiplicity, stop conditions,
rewards, duplicate traces, and infrastructure errors.

For SWE-bench Verified, require fresh-verifier provenance and reject executable
mode noise:

```bash
uv run --no-sync python user/tianhaowu/swebench_vmvm/audit_results.py \
  RESULTS --expected-tasks 500 --rollouts-per-task K \
  --require-swebench-vmvm-provenance --reject-mode-changes --strict
```

Use `K=1` for both MiniSWE and OpenHands. Then run the relevant specialized
audit:

```bash
uv run --no-sync python user/tianhaowu/swebench_vmvm/openhands_sdk_harness/audit.py \
  RESULTS --expected-rows 500 --strict
```

For SWE-rebench, use 111 tasks and five rollouts, then run both the Harbor audit
and the harness-specific audit:

```bash
uv run --no-sync python user/tianhaowu/swebench_vmvm/swe_rebench_harbor/audit.py \
  RESULTS --require-verifier-metadata --strict
uv run --no-sync python user/tianhaowu/swebench_vmvm/swe_rebench_react/audit.py \
  RESULTS --expected-rows 555 --strict
uv run --no-sync python user/tianhaowu/swebench_vmvm/audit_miniswe_native_tools.py \
  RESULTS --strict
```

Run only the ReAct or MiniSWE specialized audit that matches the evaluated
harness.

The ReAct auditor counts assistant turns without exactly one text command as
malformed. A context-limit tail may contain reasoning without text; count that
tail as malformed rather than a protocol issue when the trajectory already has
a valid command and contains no native tool call.

For OpenHands, require the evaluator step to finish as `COMPLETED` with exit
code `0:0` and exactly 500 rows. Then run
`finalize_openhands_sdk.sh`, which verifies result shape, SDK behavior,
implementation snapshots, runtime sources, inference provenance, and final
checksums.

Treat `ConversationExecutionStatus.ERROR` as valid only for clean 200-request
iteration exhaustion, or for one terminal HTTP 400 where Verifiers deliberately
stops the rollout at `context_length`. Require the latter's agent exception to
end with `rollout stopped: context_length`. Any other SDK error status, agent
exception, HTTP error, or transport error is an audit failure.

## Report progress

Report a matrix with these columns:

| Harness | Model | Benchmark | Progress | Resolved | Rate | Pass@k | Audit status | Notes |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |

For an active run, distinguish observed rate from final rate and show complete
tasks separately from rows. Do not call a result final until the exact expected
row count, zero dirty rows, all specialized audits, and checksum verification
pass.
