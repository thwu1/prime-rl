# Checkpoint-wise known-cost tag kernel

`probe_known_cost_checkpoint_kernel.py` reuses the sealed initial 174-pair
dataset while loading a completed RL HF checkpoint. It is an additive
diagnostic and cannot authorize training, evaluation, or smoke promotion.

Before any probe execution, freeze the exact 13-task primary plan:

```bash
uv run --no-sync user/tianhaowu/rsci/materialize_known_cost_checkpoint_kernel_plan.py materialize \
  --intent /checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1/submission_intent.json \
  --postrun-authority /checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1/postrun_authority.json \
  --promotion-authority /checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1/promotion_authority.json
```

Run the matched-precision reference once:

```bash
uv run --no-sync user/tianhaowu/rsci/probe_known_cost_checkpoint_kernel.py run \
  --source-probe /checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-tag-kernel-v2/probe \
  --checkpoint /checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base \
  --checkpoint-step 0 \
  --output /checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-checkpoint-kernel-v1/reference/step_0/kernel.json
```

For a trained task, wait for the complete run receipt and substitute the exact
condition and checkpoint:

```bash
RUN=/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1/block-20260808/g-p0125
uv run --no-sync user/tianhaowu/rsci/probe_known_cost_checkpoint_kernel.py run \
  --source-probe /checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-tag-kernel-v2/probe \
  --checkpoint "$RUN/weights/step_375" \
  --completion-receipt "$RUN/training_completion_receipt.json" \
  --checkpoint-step 375 \
  --output /checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-checkpoint-kernel-v1/g-p0125/step_375/kernel.json
```

Validate without modifying the artifact:

```bash
uv run --no-sync user/tianhaowu/rsci/probe_known_cost_checkpoint_kernel.py validate \
  --analysis /checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-checkpoint-kernel-v1/g-p0125/step_375/kernel.json
```

GPU jobs must be submitted only through the protected control tmux. The raw
commands above exercise the deterministic kernel implementation, but direct
interactive output is not a scientific result. Scientific execution also
requires the plan-bound per-task readiness manifest, attempt-local output,
terminal `COMPLETED/0:0` receipt, and atomic publication workflow described in
the preregistration.
