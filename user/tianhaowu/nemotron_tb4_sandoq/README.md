# Nemotron-3-Super SFT on GB300 + TB4 eval on Sandoq

Full SFT of `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16` on GB300 (g3) at 262k and 512k context,
and evaluation with mini-swe-agent 2.4.6 on the 66-task Terminal-Bench 4 (TB4 v4.0.0) set using the
Sandoq Firecracker runtime. Everything needed to reproduce lives in this folder; library fixes it
depends on are in the repo (see [Fixes](#fixes-in-the-repo)).

```
env/setup_venv.sh            build the GB300 training venv
data/prepare.sh              content-part SFT export -> renderer-ready JSONL + render check
sft/launch_sft.sh            submit an SFT run from a frozen snapshot of HEAD
sft/configs/*.toml           262k CP2 and 512k CP4 run configs (8 nodes x 4 GB300)
sft/multi_node_sft_g3.sbatch.j2   g3 Slurm template (conda Torch 2.12 stack)
sft/convert_checkpoint.sh    sbatch: DCP trainer checkpoint -> HF safetensors (convert_dcp_to_hf.py)
serve/deploy.sh              serve a checkpoint via ram_common serve_api_v2 (nemotron-3-super card)
eval/run_eval.sh             submit a TB4 eval against a deployment
eval/launch.sh               the eval job itself (cpu_x86: Sandoq provider supervisor -> Verifiers eval)
eval/nemotron_tb4.toml       eval config (agent settings mirror the SFT teacher traces)
eval/check_prompt_parity.py  served prompt tokens == SFT renderer tokens, per request
eval/aggregate.py            merge runs -> per-task table, pass@1 / pass@k, trained vs held-out
eval/tasks/                  task lists (oracle-valid 53, trained 19 / 17, retries)
oracle/                      TB4 oracle results on Sandoq and the launcher used
```

## Quick start

```bash
cd user/tianhaowu/nemotron_tb4_sandoq
env/setup_venv.sh                                  # once
data/prepare.sh <traces.sft.jsonl> /checkpoint/ram/tianhaowu/datasets/<name>
sft/launch_sft.sh sft/configs/tb4_23_overfit_262k_cp2_8node.toml tb4-23-262k-rN
# if the run saved a DCP checkpoint (skip_gather_master_weights = true):
sbatch sft/convert_checkpoint.sh /checkpoint/ram/tianhaowu/sft_nemotron_gb300/outputs/tb4-23-262k-rN 109
serve/deploy.sh tianhaowu-nemotron-tb4-sft-262k .../outputs/tb4-23-262k-rN/weights/step_109
eval/run_eval.sh tianhaowu-nemotron-tb4-sft-262k eval/tasks/trained19.tasks.txt sft262k-trained19 4
python3 eval/aggregate.py /checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/nemotron_tb4/<run dirs> \
    --tasks eval/tasks/trained19.tasks.txt
python3 ... eval/check_prompt_parity.py <run dir>/results.jsonl     # with the SFT venv python
```

## Environment

- g3 nodes: 4x GB300 (284 GB HBM each), 144 CPUs, 900 GB RAM, aarch64. Account `ram`, QOS
  `g3_ram_high`. Slurm defaults `--segment=<nodes>` (one NVL72 domain).
- Training runs on the cluster conda stack `/engshare/conda/xlformers_gbunified_conda` (Torch 2.12,
  NCCL 2.29.7, CUDA 13.1) through a `--system-site-packages` venv that adds prime-rl
  (`env/setup_venv.sh`). The pip Torch/NCCL 2.28 stack has a documented multi-rack hang.
- `mamba-ssm` must be built from source for sm_100/sm_103: it imports its CUDA extension at import
  time, and without it NemotronH silently falls back to bf16-softplus `torch_forward`.
- Triton's bundled `ptxas` does not know `sm_103a`; jobs export
  `TRITON_PTXAS_PATH=<conda>/bin/ptxas` (in the sbatch template).
- The login-node session proxy (127.0.0.1:43689) returns 403 for huggingface.co, Docker Hub and
  wandb; unset `HTTP(S)_PROXY` for downloads. Compute nodes reach them directly.
- W&B: `api.wandb.ai` is unreachable from the cluster; use `wandb login --host
  https://meta-fair.wandb.io`. Runs log offline and are synced with
  `WANDB_BASE_URL=https://meta-fair.wandb.io wandb sync --project nemotron-sft-gb300 <run>/wandb/offline-run-*`
  (entity `ram`).

## Model and data

- Weights: `/checkpoint/ram/tianhaowu/models/NVIDIA-Nemotron-3-Super-120B-A12B-BF16` (231 GB, 50 shards).
  88 layers (40 Mamba-2, 40 LatentMoE with 512 experts top-22, 8 GQA attention with 2 KV heads, no RoPE).
- Data: `ThWu/tmp` -> `nemotron-tb4-23-overfit-174-20260926`: 174 GLM-5.3-Flash mini-swe-agent
  traces (reward 1) over **19 TB4 tasks**, the set used for the Tinker overfit run. Two overlength
  rows (uefi-bootkit 282k, risk-scorer-replay 270k tokens) were dropped by the exporter.
- The export stores assistant reasoning as `{"type": "thinking"}` content parts, which the
  nemotron-3 renderer cannot read (it crashes). `data/convert_parts.py` moves thinking into
  `reasoning_content` and joins text parts. Converted copy:
  `/checkpoint/ram/tianhaowu/datasets/nemotron-tb4-23-overfit-174-prime/train/train.jsonl`.
- Renderer check (`data/check_render.py`, all 174 rows): every thinking/text/tool-call token of every
  assistant turn is trained (including `<|im_end|>`), no system/user/tool text is trained. Rendered
  lengths 14,753..261,561 tokens (mean 114,569).

## SFT

| | 262k | 512k |
|---|---|---|
| config | `tb4_23_overfit_262k_cp2_8node.toml` | `tb4_23_overfit_512k_cp4_8node.toml` |
| GPUs | 8 nodes x 4 | 8 nodes x 4 |
| parallelism | EP 8, CP 2 (Ulysses), FSDP CPU offload | EP 8, CP 4 (Ulysses, KV heads replicated 2->4) |
| batch | 16 rows (one trajectory per data rank) | 8 rows |
| steps | 109 = 10 epochs | 218 = 10 epochs (matches Tinker batch 8 / 220 updates) |
| peak memory | ~173 / 277 GiB | ~174 / 277 GiB |
| step time | ~94 s | ~120 s |

Common: LR 1e-5 linear (5 warmup), `loss_impl = "chunked"`, full activation checkpointing with
offload, `moe_use_grouped_mm = false`, `fixed_stack` packing, nemotron-3 renderer with
`preserve_all_thinking = true`.

Notes:
- Ulysses CP requires `cp` to divide the KV head count (2); `ulysses_attn` now replicates KV heads
  when `cp` is a multiple of it, so CP4/CP8 work (checked against full attention for cp 2/4/8).
- Mamba CP previously ignored packed-sequence boundaries; it now takes the full-sequence
  `cu_seqlens`, so `cat` packing is correct under CP. The configs still use `fixed_stack`.
- Logged metrics to discount: `MFU` (~690%) uses A100 peak FLOPs for GB300, charges attention on all
  88 layers and counts padding (real MFU ~3%); `Max Vio` is dominated by padding tokens (0.7 on real
  tokens vs ~27 padded, measured with `sft/probe_routing_padding.py`); the step-0 routing stats of
  runs before `967a56f83` are uninitialized memory.
- Launch runs with `sft/launch_sft.sh`: the venv imports prime-rl from the dev checkout, and a job
  that started while that checkout was being edited crashed with a NameError.

### Checkpointing

The first 262k run trained all 109 steps (loss 1.18 -> 0.05) and then lost its weights: the HF
weight save gathered the full bf16 model on rank 0 and the node ran out of host RAM
(`sacct` `OUT_OF_MEMORY`, ~850 GiB MaxRSS) next to the FSDP CPU-offloaded training state.

- `be1949dec` makes `WeightCheckpointManager` save layer by layer (gather, `convert_layer_to_hf`,
  write one shard per layer); rank 0 holds about one layer. Output is bit-identical to the gathered
  save (8-layer test, 3137/3137 tensors). Full-scale check (job 1623922, 120B on 8 nodes): the
  step-1 save took 441 s, and the 41,643 tensors match the base checkpoint's dtypes and shapes (only
  the 1,040 `mtp.*` speculative-decoding weights are absent, as with the gathered save). Mid-run
  saves (`ckpt.interval`) use the same path.
- The -r2 runs (started before that fix) save a final DCP checkpoint instead
  (`skip_gather_master_weights = true`); `sft/convert_checkpoint.sh` converts it, streaming one layer
  at a time (bit-identical to the gathered save on the same test). New runs use the default HF
  weight save (see the honeycomb config: streamed HF weights every epoch).

### Honeycomb run

`sft/configs/honeycomb_213_262k_cp2_8node.toml`: 213 traces (`nemotron-honeycomb-216-20260929`,
filtered to <= 256k tokens and no CJK) over 43 synthetic variants of 5 TB4 tasks (embedding-drift-
monitor, mvcc-lsm-compaction, protein-autointerp-disulfide, wal-recovery-ordering, fin-saccr-rwa).
The real TB4 tasks are held out, so `eval/tasks/honeycomb_targets5.tasks.txt` measures transfer.
5 epochs = 67 steps, HF weights every 14 steps and at the end. Prepared data:
`/checkpoint/ram/tianhaowu/datasets/nemotron-honeycomb-213-prime` (one context-only assistant turn
is `trainable: false` by design).

## Serving

`serve/deploy.sh` deploys through `ram_common/vllm_tools/serve_api_v2` with
`serve/nemotron-3-super.card.toml` (branch `feat/nemotron-3-super-card` in
`/storage/home/tianhaowu/ram_common-nemotron`): `vllm/vllm-openai:v0.20.1`, TP 4 on one g3 node,
`tool_call_parser = qwen3_coder` (the `<tool_call><function=bash><parameter=command>` format the SFT
data uses), `reasoning_parser = nemotron_v3`, `mamba-ssm-cache-dtype = float32`, max-model-len 262144.
The base deployment `tianhaowu-nemotron-super-base-probe` is at `http://cpu-128-021:8107`.

## Eval harness

`eval/launch.sh` runs on `cpu_x86`: the Sandoq provider supervisor
(`kimi_sandoq_firecracker_host.json`, lease profile `kimi-tb4-long`) wraps the Verifiers v1 eval with
the mini-swe-agent 2.4.6 harness (`mini.yaml`, tool calling), Firecracker host networking and the
native Sandoq tunnel. Settings mirror the teacher traces: `step_limit = 300`, 600 s per command,
parallel tool calls allowed, `temperature = 1.0`, `top_p = 1.0`, 32k max tokens per response, 262k
context, thinking on.

Required for the served prompt to equal the SFT rendering (verified with `check_prompt_parity.py`:
`usage.prompt_tokens` equals the renderer length on every turn):
- `[client] assistant_reasoning_field = "reasoning"`: litellm inside mini-swe-agent replays prior
  thinking as `reasoning_content`, which vLLM 0.20 ignores, so every past turn was served as
  `<think></think>` (by turn 5 the prompt was 4,345 tokens instead of 8,653).
- `[taskset] prompt_style = "harbor"`: strip the harbor-canary comment, keep the trailing newline;
  reproduces the teacher task text on all 174 SFT rows. The only remaining difference is the
  `<system_information>` kernel string, which comes from the sandbox.

Other required settings:
- Resources clamped to the Sandoq grant (`resource_*_cap`: 4 CPU / 7914 MB / 58829 MB, from capacity
  probe job 1554280). Tasks declaring more fail provisioning; the oracle ran every task clamped.
- `enable_compose = false`: Sandoq has no Compose; the two oracle-valid compose tasks pass without
  their sidecar.

## Oracle (TB4 v4.0.0 on Sandoq)

53 / 66 tasks pass (`oracle/tb66_oracle_results.tsv`, runs under
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/tb66_oracle_20260929/`), including all 19 trained tasks.

| class | count | tasks |
|---|---|---|
| pass | 53 | `eval/tasks/oracle53.tasks.txt` |
| Docker Compose sidecar | 9 | ctr-optimization, freight-dispatch-shift, heat-pump-warranty, intrastat-meldung, kv-live-surgery, legacy-utility-triage, live-database-cutover, medical-claims-processing, payments-pipeline-fix |
| GPU | 3 | fp8-rmsnorm-gemm, jax-speedrun-gpu, math-eval-grader |
| Sandoq `/shared` mount hides task files | 1 | vba-userform-port |

`batched-eval-parity` and `lake-temp-glm` declare a no-network verifier; on Sandoq they run under the
audited public-network override (verifier has internet), approved for this eval.
`oracle/launch_oracle.sh` expects the `/storage/home/tianhaowu/prime-tb66-oracle` worktree (branch
`tb66-oracle-20260929`), whose oracle-runner changes (host task network, tunnel shape) build on
`fix/kimi-production-resource-coverage` and are not on vmvm-sandbox.

## Results so far

Training (262k, first run; the -r2 rerun reproduces it step for step): loss 1.18 -> 0.58 (step 36)
-> 0.26 (step 69) -> 0.05 (step 108); grad norm ~0.3 after warmup, occasional clipped spikes.
W&B: https://meta-fair.wandb.io/ram/nemotron-sft-gb300 (runs `75v9lcd0` 262k, `seezxvlq` 512k first
attempt; -r2 runs sync the same way).

Base Nemotron-3-Super, pass@1 on oracle-valid tasks (runs under
`/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/nemotron_tb4/`): 0 solved of 42 scored so far,
0 / 19 trained tasks. Rollouts mostly end with a wrong submission; ~11 hit the 262k context limit.
SFT evaluation: 4 rollouts per trained task, compared with 4 base rollouts on the same tasks.

## Fixes in the repo

On `vmvm-sandbox` (thwu1/prime-rl) unless noted:

| commit | fix |
|---|---|
| `72a0af128` | Ulysses KV-head replication (`ulysses_attn.py`); Mamba CP honors packed `cu_seqlens` (`cp_mamba.py`) |
| `967a56f83` | zero NemotronH MoE routing stats after meta init |
| `be1949dec` | layer-by-layer HF weight checkpoint save (`ckpt.py`, `weights.py`) |
| `b5ffa133f` | taskset `prompt_style = "harbor"` |
| `278a1ac9` | verifiers `EvalClientConfig.assistant_reasoning_field` (thwu1/verifiers `fix/sandoq-buffered-stats-sink-20260927`, pinned by vmvm-sandbox) |
| `cd504c4aa` | Sandoq background jobs run in non-login bash (image `ENV PATH` kept) |
| `97da3263b` | Harbor-style artifact dir modes for separate verifiers |
| `164dc6b46`, `85229b13b`, `95b6304fe` | non-root image users on Sandoq: tmux `SHELL=/bin/bash`, root harness setup via `podman exec --user 0`, runner tmux kept out of the task's `/tmp` (fixed risk-scorer-replay, rs-archive-clone) |
