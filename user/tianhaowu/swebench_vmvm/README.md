# SWE benchmarks on VMVM

All benchmark-specific code for SWE-bench Verified and SWE-rebench lives in this
directory. The launchers compose the existing Verifiers v1 VMVM runtime and do
not add benchmark conditionals to the shared runtime or existing DeepSWE
harnesses.

| Benchmark | Agent and model | Workload | Reproduction target |
| --- | --- | ---: | ---: |
| SWE-bench Verified | mini-swe-agent 2.2.8 + Nemotron 3 Super | 500 x 1 | about 55% |
| SWE-bench Verified | OpenHands SDK 1.17.0 + Nemotron 3 Super | 500 x 3 | 60.47% |
| SWE-rebench July 2026 | published ReAct scaffold + Qwen3.6-27B | 111 x 5 | 31.2% |

The CPU evaluator talks directly to an OpenAI-compatible prime-rl inference
endpoint. Model calls made inside a VMVM task are intercepted by Verifiers and
forwarded through the VMVM reverse tunnel. Run evaluation drivers through Slurm,
not on a login node.

## Common launcher

`run_v1_eval.sbatch` accepts either an inference job ID or an explicit endpoint:

```bash
sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,EVAL_CONFIG=CONFIG \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch

sbatch --export=ALL,INFERENCE_BASE_URL=http://HOST:8000/v1,EVAL_CONFIG=CONFIG \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
```

Set `OUTPUT_DIR` to override the default
`/checkpoint/ram/tianhaowu/swebench_vmvm/evals/run_JOB_ID`. On days when VMVM
lease renewal is unstable, pass `VMVM_LEASE_TTL=10m`; the configs retain the
normal 60-second default. The launcher holds an exclusive lock for the selected
output directory and refuses to truncate an existing `results.jsonl` on a fresh
run.

If an inference allocation is lost, resume the durable result directory after
the replacement endpoint is healthy:

```bash
sbatch --export=ALL,INFERENCE_BASE_URL=http://NEW_HOST:8000/v1,\
RESUME_DIR=/checkpoint/ram/tianhaowu/swebench_vmvm/evals/run_OLD_JOB_ID \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
```

The launcher keeps completed, error-free rows, reruns only missing or errored
rollouts, saves the previous `config.toml`, and records the replacement
server's `/v1/models` response separately.

When the researcher explicitly permits using GPU allocations for the evaluator
and the CPU queue is blocked, an interrupted OpenHands run can use spare host
resources in its dedicated, exclusive inference allocation. Cancel every other
writer first, then launch `run_colocated_openhands_resume.sh` as an overlapping
Slurm step. The wrapper runs native resume, targeted repair, and both terminal
audits sequentially; it hides the GPUs from the evaluator and writes an atomic
status receipt under `colocated_openhands/`.
`run_colocated_qwen_repair.sh` provides the corresponding post-run path for the
Qwen MiniSWE comparison. It refuses to start while the original evaluator is
still active, gates resume on the corrected Go and Gradle oracle tasks, reruns
only missing or errored rows, and writes strict shape and native-tool audits.

## SWE-bench Verified with mini-swe-agent

The MiniSWE path uses the isolated `swebench-verified-vmvm` taskset, the
official SWE-bench images, and the built-in `swebench.yaml` prompt. The taskset
rebuilds the Git index from the instance base commit with `core.fileMode=false`,
then extracts the candidate diff, including full binary payloads, after the agent
exits and evaluates it in a second, fresh VMVM container at the instance's base commit. This matches SWE-bench's
clean evaluation-container boundary and prevents package or environment changes
made by an agent from corrupting verifier results. Missing or malformed verifier
artifacts are errors rather than zero scores.
The production config allows eight hours for the agent rollout and nine hours
for its VMVM session. Some 250-turn trajectories exceed four hours; cutting the
outer runtime off earlier converts an otherwise valid long-horizon attempt into
an infrastructure retry before MiniSWE reaches its own turn limit.

Run the smoke:

```bash
sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,\
EVAL_CONFIG=user/tianhaowu/swebench_vmvm/mini_swe_smoke.toml,\
VMVM_LEASE_TTL=10m \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
```

Run all 500 tasks:

```bash
sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,\
EVAL_CONFIG=user/tianhaowu/swebench_vmvm/mini_swe.toml,\
VMVM_LEASE_TTL=10m \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
```

## SWE-bench Verified with OpenHands

The canonical 60.47% reproduction uses NVIDIA's published NeMo Evaluator
recipe, not the older NeMo Gym `nv-OpenHands` wrapper. The isolated
`openhands_sdk_harness/` implementation mirrors the public recipe at NeMo Gym
commit `354babf7e3554fcd006807c86e80ef476aec9408` and NeMo Evaluator commit
`230c8411fff82fa581195b7d088d7fb67d3bc98c`: OpenHands SDK 1.17.0, Terminal,
FileEditor, and TaskTracker tools, 200 iterations, a 1,800-second command
ceiling, a three-hour run ceiling, and the published system/instruction
prompts. Its local request adapter also reproduces the recipe's system-message
replacement, turn warnings, parameter removal, `temperature=1.0`,
`top_p=0.95`, thinking enablement, and cross-turn `think_tags` reasoning replay.
Render the instruction from the stripped seeded task prompt, matching NeMo
Evaluator rather than the newline-preserving `tests/config.json` copy.
The SDK harness sets the task repository's local `core.fileMode=false` before
the agent starts. VMVM exposes some SWE-bench image files with permissive mode
bits; without this setting an agent-side `git stash` can turn those container
permissions into a large, synthetic executable-bit patch. Candidate-patch
capture rebuilds the index from the base commit and forces the same Git setting;
the SDK audit rejects residual `old mode`/`new mode` entries.

Build the pinned relocatable SDK environment once:

```bash
sbatch user/tianhaowu/swebench_vmvm/setup_openhands_sdk.sbatch
```

Run a smoke, then the three-repeat reproduction:

```bash
sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,\
EVAL_CONFIG=user/tianhaowu/swebench_vmvm/openhands_sdk_official_smoke.toml,\
VMVM_LEASE_TTL=10m \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch

sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,\
EVAL_CONFIG=user/tianhaowu/swebench_vmvm/openhands_sdk_official.toml,\
VMVM_LEASE_TTL=10m \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
```

`openhands_sdk_official.toml` uses three repeats over all 500 tasks for the
reported-score comparison. `openhands_sdk_official_5x.toml` mirrors the current
public recipe's five-repeat setting. Audit the SDK and request-transform
contract in addition to the normal VMVM provenance audit. For every request,
the SDK audit reconstructs the exact merged system message, including the
turn-specific 160--189 and 190--200 warnings, and verifies its SHA-256 digest:

```bash
uv run --no-sync python \
  user/tianhaowu/swebench_vmvm/openhands_sdk_harness/audit.py \
  /path/to/results.jsonl --expected-rows 1500 --strict
```

For a new run, `run_v1_eval.sbatch` records a deterministic implementation
archive, complete file manifest, and repository revisions before starting the
evaluator. After the evaluator has exited, run the combined fail-closed finalizer. It
performs both audits and hashes the results, configuration, model snapshots,
saved implementation snapshot, and required `inference_*` launch evidence. It
also archives and verifies the exact finalizer/auditor sources used at
completion. A separate completion-time source archive records the VMVM backend,
Verifiers v1, and SWE-bench taskset dependency code plus their repository
revisions. The finalizer verifies all nested implementation, runtime-source,
and inference manifests before writing the final checksum manifest. Both source
archives must contain exactly their manifested regular files. Both source
manifests are checked again after all audits run, rejecting an audit-time source
mutation:

```bash
BASE_RESULTS_DIR=/path/to/completed/run \
  bash user/tianhaowu/swebench_vmvm/finalize_openhands_sdk.sh
```

For a long colocated run, `watch_finalize_openhands_sdk.sh` can wait for the
known evaluator Slurm step to exit. It requires that exact step to finish as
`COMPLETED` with exit code `0:0`, refuses a short result, and records an atomic
`finalizer_status.json` before returning.

The earlier OpenHands path pins NVIDIA's `sdevare-nv/nv-OpenHands` checkout at commit
`5f0180054732945df08ad2293903e6873f0492b6`, CodeActAgent, 100 iterations, and
the v0.62 tmux SWE-bench evaluator. It remains a diagnostic baseline and is not
the canonical 60.47% reproduction. Build that relocatable runtime with:

```bash
sbatch user/tianhaowu/swebench_vmvm/setup_openhands.sbatch
```

The resulting archive contains the Poetry project virtualenv and Git metadata
required by the official evaluator. The isolated runner configures its Python
path, tmux environment, and Git safe-directory entry after extraction.
The full config keeps OpenHands' upstream eight-hour per-instance ceiling;
shorter outer deadlines can terminate valid 100-iteration trajectories before
the agent emits its patch.
OpenHands sends model requests itself, so the outer Verifiers sampling table is
not sufficient. The harness also sets the 262,144-token input window, enables
thinking without truncating prior thinking, preserves special tokens, and uses
the model-card temperature 1.0/top-p 0.95 settings in OpenHands' own LLM config.

Run the one-task smoke:

```bash
sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,\
EVAL_CONFIG=user/tianhaowu/swebench_vmvm/openhands_reasoning_smoke.toml,\
VMVM_LEASE_TTL=10m \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
```

Run all 500 tasks:

```bash
sbatch --export=ALL,INFERENCE_JOB_ID=JOB_ID,\
EVAL_CONFIG=user/tianhaowu/swebench_vmvm/openhands_reasoning.toml,\
VMVM_LEASE_TTL=10m \
  user/tianhaowu/swebench_vmvm/run_v1_eval.sbatch
```

The legacy v0.62 diagnostic configs use the isolated
`openhands_harness_reasoning/` bridge. OpenHands v0.62 needs parsed reasoning
folded into response content while it converts the response into an action, but
that folded text must be restored to `reasoning_content` before the next model
request. Otherwise Nemotron renders historical thinking as visible answer text
after an empty `<think></think>` block. The bridge tracks the original fields by
tool-call ID, requests generation token IDs as a fallback, and records counters
in `info.openhands_reasoning_history`. Audit a completed result with:

```bash
uv run --no-sync python \
  user/tianhaowu/swebench_vmvm/openhands_harness_reasoning/audit_reasoning.py \
  /path/to/results.jsonl --strict
```

`openhands.toml` and `openhands_smoke.toml` retain the original direct bridge as
diagnostic controls; do not use their score as the canonical reproduction.

The legacy NeMo Gym v0.62 OpenHands configuration injects only the model,
endpoint, temperature, top-p, and output-token limit. It does not publish a
`top_k`, special-token decoding override, or history-thinking override. The isolated
`openhands_harness_public_defaults/` adapter and
`openhands_public_defaults_{smoke,100}.toml` configs test those public defaults
without changing the active full-run harness. Treat this as a diagnostic until
its matched-task comparison is complete; it is not the newer OpenHands SDK
recipe used for the 60.47% reproduction.

Compare its 100 rows against the same tasks from the canonical run:

```bash
uv run --no-sync python \
  user/tianhaowu/swebench_vmvm/compare_one_rollout_results.py \
  /path/to/canonical/results.jsonl /path/to/public-default/results.jsonl \
  --expected-common-tasks 100 --strict
```

The report includes matched solve rates, paired wins/losses, and the exact
two-sided McNemar p-value.

OpenHands writes its candidate patch in its own workspace. The harness extracts
the staged, binary-capable Git diff directly from that workspace, compares its digest with the
serialized OpenHands result, applies OpenHands' line-ending/prefix
normalization, and applies only the patch to `/testbed`. The taskset then copies
the resulting candidate diff into a fresh VMVM verifier container. Candidate
patch metadata and the parsed SWE-bench test report are retained in the result
row. An invalid model-generated patch is scored against the unchanged
repository instead of being reported as a sandbox outage.

Require that isolation evidence on every completed SWE-bench result:

```bash
uv run --no-sync python user/tianhaowu/swebench_vmvm/audit_results.py \
  /path/to/results.jsonl --expected-tasks 500 --rollouts-per-task 1 \
  --require-swebench-vmvm-provenance --strict
```

This verifies the candidate-patch byte count and SHA-256, the fresh verifier
runtime descriptor, the parsed test report, and agreement between the report
and persisted reward. It also requires a distinct verifier-container descriptor
for every row.

For the official Nemotron configuration, launch the isolated single-node H100
server and wait for `/v1/models` to become healthy:

```bash
sbatch user/tianhaowu/swebench_vmvm/run_nemotron_inference_h100.sbatch
```

This launcher preserves the model-card `qwen3_coder` tool parser and
`nemotron_v3` reasoning parser. Do not launch this reproduction through the
shared generated multi-node template: that template currently overrides the
configured tool parser with `qwen3_xml`, which changes agent behavior.

## SWE-rebench July 2026

The canonical source is the pinned Harbor package
`ibragim-badertdinov/swe-rebench-07-2026@2026-07`. It contains 111 tasks across
Go, Java, Python, Rust, and TypeScript and uses the native
`docker.io/swerebenchv2/*` images.
It is not stored in SWE-bench Verified's row format. The adapter converts each
Harbor task into the same Verifiers `Task` contract used by the Verified run,
while retaining SWE-rebench's native image, workdir, environment, and verifier.

Download and export it:

```bash
sbatch user/tianhaowu/swebench_vmvm/download_swe_rebench_harbor.sbatch
```

The custom Harbor taskset derives each repository workdir from
`tests/config.json`. It stages the verifier under `/tests` but executes
`/tests/test.sh` from the repository root, matching the SWE-rebench v2 verifier
contract. It also preserves each task's declared solution and verifier
environment. Java tasks use the VMVM host's forward-proxy CA and a Google Maven
Central mirror for Maven and Gradle dependencies because the cluster proxy
rate-limits the canonical Central hosts. Gradle searches that mirror before,
but still retains, Plugin Portal in settings, project, and buildscript
repositories so non-Central plugin markers remain available; transient
repository failures are retried before they become evaluation errors. That
project/buildscript fallback is injected only for Apache Pulsar, which requires
it. Other Java projects do not receive a Plugin Portal repository that could
redirect ordinary dynamic dependencies to the rate-limited canonical Central
host.
The benchmark-local compatibility module installs the Java CA and supplies the
VMVM tunnel's narrow socket-probe shim when a Go, Java, Rust, or TypeScript image
does not include Python. No shared VMVM backend modification is required.
The verifier setup reuses an available `python3` or the uv installed by the
agent harness. It bootstraps uv only when neither exists, avoiding a redundant
network install in the bounded finalize phase.

From a Slurm worker, validate those folder-local VMVM adaptations against an
unchanged shared runtime with:

```bash
uv run --no-sync python user/tianhaowu/swebench_vmvm/validate_vmvm_compat.py \
  --image docker.io/swerebenchv2/openrewrite__rewrite-7784:v0.1.0 \
  --workdir /rewrite --require-python-missing --check-java-ca
```

`swe_rebench_harbor/audit.py` verifies that every persisted task field matches
the pinned Harbor source and that each task has the configured rollout count.
For runs produced by the current taskset, pass `--require-verifier-metadata` to
also require exact agreement between the verifier record and persisted reward.

Validate an oracle solution before model evaluation:

```bash
sbatch --export=ALL,TASKS=Soju06__codex-lb-744,VMVM_LEASE_TTL=10m \
  user/tianhaowu/swebench_vmvm/validate_swe_rebench.sbatch
```

The public benchmark implementation is
[`SWE-rebench/SWE-rebench-V2`](https://github.com/SWE-rebench/SWE-rebench-V2),
with its compatible grader in
[`SWE-rebench/SWE-bench-fork`](https://github.com/SWE-rebench/SWE-bench-fork).
Those repositories publish the task construction and grading machinery, but
not Qwen's executable agent: the Qwen3.6 model card calls it an "internal agent
scaffold (bash + file-edit tools)." The local `swe_rebench_react/` runner is
therefore a behavior-compatible implementation of the published fixed
text-command ReAct interface, not vendored upstream agent code. It uses the
appendix system prompt verbatim (SHA-256
`dbae17152474bee3819551922242c3fd4189727114442d86b7b3ff75e649ee6c`), the
250-step limit, Qwen's recommended sampling settings, and the leaderboard's
standardized 128K context window. Run its one-task smoke with
`swe_rebench_qwen36_smoke.toml`; run the complete 111-task, five-rollout
evaluation with `swe_rebench_qwen36.toml`. The
`swe_rebench_qwen36_java_smoke.toml` config targets a Java image and should be
used after VMVM tunnel or proxy changes.

Audit a completed five-rollout result against the fixed system prompt, model
and sampling configuration, VMVM runtime, initial task-message rendering, and
text-command protocol:

```bash
uv run --no-sync python \
  user/tianhaowu/swebench_vmvm/swe_rebench_react/audit.py \
  /path/to/results.jsonl --expected-rows 555 --strict
```

A request that reaches or crosses the 131,072-token boundary can appear as a
vLLM 400 in the server log, either as an overlong prompt or as
`max_tokens must be at least 1, got 0`. The benchmark-local compatibility module
maps both responses to a clean `context_length` stop; they are model-budget
outcomes, not rows to repair or retry.

`swe_rebench_miniswe/` is retained as an optional compatibility runner for the
older mini-swe-agent 1.14.4 interface. The primary mini-swe-agent comparison is
`swe_rebench_qwen36_miniswe.toml`: it runs mini-swe-agent 2.2.8's native `bash`
tool-calling `swebench.yaml` scaffold for the same 111 tasks and five rollouts.
That comparison is separate from the text-command ReAct reproduction above.
Audit the completed native-tool result with:

```bash
uv run --no-sync python \
  user/tianhaowu/swebench_vmvm/swe_rebench_miniswe/audit_native_tools.py \
  /path/to/results.jsonl --strict
```

The audit requires at least one successfully executed native `bash` call per
rollout, unique call IDs, and a linked tool result for every ordinary valid
call. The terminal `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` call intentionally
has no tool-result node because it exits the agent. The audit also reports
malformed model-generated calls. A malformed call is accepted by the strict
audit only when mini-swe-agent immediately records its standard `Tool call
error` corrective message; an unhandled malformed call still fails the audit.
Mini-swe-agent rejects the complete assistant response when one member of a
multi-call response is invalid, so valid `bash` siblings in that response are
reported as rejected and do not require tool-result nodes.
If the framework reaches the configured turn limit immediately after sampling
a final tool call, that unexecuted call is reported separately as a valid
budget-limit outcome. The same applies to the final call preceding a clean
`context_length` or `harness_timeout` stop, where no later request exists to
round-trip the tool result into the captured conversation.

### Qwen inference on H100 or H200

Both GPU types expose the same model ID and the leaderboard's standardized
131,072-token context contract:

- `qwen36_inference_h100.toml`: four H100 nodes, with the checkpoint read from
  the shared offline H100 cache.
- `qwen36_inference_h100_single.toml`: one H100 node with the same TP8 model.
- `qwen36_inference_h200_single.toml`: equivalent one-node H200 fallback for
  scheduler preemption or queue pressure; it is sufficient for the
  evaluation's 16-worker concurrency when four contiguous nodes are slow to
  schedule.
- `qwen36_inference.toml`: four H200 nodes.
- `qwen36_inference_h100_smoke.toml`: one H100 node for a short validation.
- `qwen36_native_tools_inference_h100.toml`: one H100 node with the
  `qwen3_coder` tool parser and `qwen3` reasoning parser, required by the
  mini-swe-agent native-tool comparison. Launch it with
  `run_qwen36_native_tools_inference_h100.sbatch` rather than the generated
  shared template, which currently forces `qwen3_xml`.
- `qwen36_native_tools_inference_h200.toml`: four-GPU H200 fallback for the same
  native-tool endpoint, launched with
  `run_qwen36_native_tools_inference_h200.sbatch`.

Render and submit the selected server:

```bash
uv run --no-sync inference @ user/tianhaowu/swebench_vmvm/qwen36_inference_h100.toml --dry-run
bash -n /checkpoint/ram/tianhaowu/swebench_vmvm/qwen36_inference_h100/inference.sbatch
sbatch --qos=h100_ram_high --no-requeue \
  /checkpoint/ram/tianhaowu/swebench_vmvm/qwen36_inference_h100/inference.sbatch
```

Replace the config and generated path with `qwen36_inference.toml` and
`qwen36_inference/` to use H200. Wait for `/v1/models` to advertise
`Qwen/Qwen3.6-27B`, then launch the smoke or full evaluation through the common
launcher. Use `--no-requeue`: after a Slurm requeue the inference server may
move to another node while an active evaluator keeps the old URL. If that
happens, stop the evaluator, wait for the server to become healthy, and resume
the durable evaluation directory so only missing or errored rollouts are run.
An output directory must have exactly one writer. The launcher enforces this
with an exclusive lock, but still confirm that an evaluator started by older
code or another tool is terminal before resuming. Two uncoordinated resume
processes can take the same owed-task snapshot and append duplicate indices with
different sampled rewards. When ownership is uncertain, launch a fresh output
directory and retain the old partial as non-canonical evidence.
For a long full run, use a non-preemptible QOS available to the account; two
preemptions under `h100_lowest` were enough to interrupt otherwise healthy
rollouts.

## Result checks

For a completed or running result file, use the benchmark-aware audit instead
of counting only lines. It validates task indices, rollout multiplicity, unique
trace IDs, stop conditions, and infrastructure errors:

```bash
uv run --no-sync user/tianhaowu/swebench_vmvm/audit_results.py \
  /checkpoint/ram/tianhaowu/swebench_vmvm/evals/run_JOB_ID/results.jsonl \
  --expected-tasks 500 --rollouts-per-task 1 \
  --require-swebench-vmvm-provenance --reject-mode-changes --strict
```

Use `--rollouts-per-task 3` for the official OpenHands SDK run. Omit `--strict`
while a run is still in progress. For SWE-rebench, use `--expected-tasks 111
--rollouts-per-task 5` and omit the SWE-bench-specific provenance flag.

SWE-rebench's aggregate score is resolved rollouts divided by 555. SWE-bench
Verified uses resolved tasks divided by 500. Infrastructure or harness errors
must be zero before comparing either score with its target.

If a one-rollout run needs targeted repair, keep the original result immutable
and create a canonical merged file:

```bash
uv run --no-sync user/tianhaowu/swebench_vmvm/merge_one_rollout_repairs.py \
  /path/to/original/results.jsonl /path/to/repair/results.jsonl \
  --output /path/to/canonical/results.jsonl --expected-tasks 500 \
  --reject-mode-changes
```

The merge rejects duplicate, unknown, or dirty repair rows and writes SHA-256
provenance beside the canonical JSONL.

To repair otherwise-valid SWE-bench rows that contain VMVM executable-bit
noise, pass `--include-mode-changes` to `make_repair_config.py`. Audit the
replacement run with `audit_results.py --reject-mode-changes` before merging it;
the merge flag independently refuses either repaired or retained rows that
still contain mode changes.

For the 93-row MiniSWE executable-bit repair, the combined finalizer audits the
repair, creates the immutable 500-row merge, audits it again, and records all
source/result/model checksums:

```bash
BASE_RESULTS_DIR=/path/to/original/run \
REPAIR_RESULTS_DIR=/path/to/completed/repair \
  bash user/tianhaowu/swebench_vmvm/finalize_miniswe_mode_repair.sh
```

For OpenHands, `repair_openhands.sbatch` automates this after a completed full
run: it derives the dirty task list, runs only those tasks with the current
eight-hour timeout config, merges by task name while restoring the original
task indices, and performs a strict 500-row audit. It can be dependency-chained
without modifying the original run:

```bash
sbatch --dependency=afterany:FULL_EVAL_JOB_ID \
  --export=ALL,INFERENCE_JOB_ID=INFERENCE_JOB_ID,BASE_RESULTS_DIR=/path/to/full/run \
  user/tianhaowu/swebench_vmvm/repair_openhands.sbatch
```

The repair launcher defaults to `openhands_reasoning.toml` and writes both the
ordinary strict result audit and the reasoning-history audit. Set
`SOURCE_CONFIG` explicitly only when repairing a non-canonical diagnostic run.
Only serialized errors and an explicit `error` stop are dirty. A
`harness_timeout` row that finalized, produced a binary reward, and completed
scoring is a valid budget-limited outcome and must not be resampled.

For an existing queued repair created before the provenance gate was added,
chain `audit_openhands_canonical.sbatch` after it. The audit selects the
canonical merge when present, otherwise the original complete result, and
writes strict VMVM-provenance, reasoning-history, and SHA-256 reports beside
the selected artifact.
