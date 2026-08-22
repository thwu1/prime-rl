# Standalone DeepSWE OpenHands harness

This harness runs OpenHands SDK as a Pier agent without changing the existing
MiniSWE evaluation path. Pier still owns the DeepSWE dataset, sandbox provider,
hidden verifier sandbox, retries, and result aggregation. The OpenHands process
runs locally inside each task sandbox with TerminalTool and FileEditorTool.

The production VMVM config uses 113 concurrent tasks, six infrastructure-only
retries, 200 OpenHands iterations, a three-hour agent timeout, a four-hour
sandbox ceiling, and Nemotron's native 262,144-token context limit:

```bash
sbatch user/tianhaowu/deepswe_openhands/submit_eval.sbatch \
  user/tianhaowu/deepswe_openhands/nemotron_super_deepswe_vmvm.toml
```

Run the one-task gate first:

```bash
sbatch user/tianhaowu/deepswe_openhands/submit_eval.sbatch \
  user/tianhaowu/deepswe_openhands/nemotron_super_deepswe_vmvm_smoke.toml
```

Validate config rendering without launching:

```bash
uv run --no-sync python user/tianhaowu/deepswe_openhands/submit_eval.py \
  user/tianhaowu/deepswe_openhands/nemotron_super_deepswe_vmvm.toml --dry-run
```

The TOML may select `modal`, `vmvm`, or `sandoq`; `--provider` overrides it.
The stable provider/runtime implementation and RAM inference gateway are reused,
but all OpenHands agent, launcher, prompt, configuration, and trajectory code is
contained in this directory.
`sandbox_startup_timeout_sec` also scales Pier's outer environment-build and
agent-setup watchdogs from their 1,800- and 360-second defaults, so provider
startup and package installation are not cancelled before the configured
VMVM/Sandoq startup ceiling.

## Thinking and trajectory contract

The runner disables condensation and serializes every prior assistant
`reasoning_content` block into the request. OpenHands 1.42.1 does not recognize
the private gateway model alias as an interleaved-thinking model, so the pinned
runner explicitly enables its reasoning-history serializer and performs a
synthetic serializer assertion before the first model call. With
`thinking.preserve_previous = true`, every real request carries:

```json
{"enable_thinking": true, "truncate_history_thinking": false}
```

Set `thinking.preserve_previous = false` for the no-preserve ablation. The
runner leaves the private model alias out of OpenHands' reasoning-history
allowlist, verifies that its serializer omits prior `reasoning_content`, and
also sends `truncate_history_thinking=true` as a fail-closed renderer setting.
The terminal capture audit fails if any prior reasoning text remains visible.

The CPU capture proxy independently verifies the reasoning prefix on every
request and renders each final request through the live vLLM renderer. Driver
artifacts are under
`/checkpoint/ram/tianhaowu/deepswe_eval/openhands-driver/JOB_ID/`.

Each trial records `openhands-events.json`, `openhands-trajectory.json`, raw
completion logs, metrics, the serializer assertion, a Pier ATIF `trajectory.json`,
and `submission-commit.txt`. Finished, iteration-limited, and native
context-limited runs commit the current patch before DeepSWE verification;
other agent failures remain failures and are not resampled as infrastructure.
The adapter disables Git file-mode tracking before the agent starts so VMVM
image permission differences cannot become synthetic patch changes.
If OpenHands exhausts its internal retries and its exit report explicitly shows
a transient API transport or service failure, the Pier adapter raises
`SandboxError` so the configured whole-trial retry can recover it.
