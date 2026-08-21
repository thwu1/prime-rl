---
name: tau3-banking
description: Launch, resume, monitor, and audit the standalone Tau3 Banking benchmark on VMVM with an external policy server and Kimi user/judge endpoints. Use for the 97-task banking_knowledge suite, Tau2 v1.0.1 parity, Nemotron Super evaluation, exact-once VMVM recovery, pass@k reporting, or investigating the 16-tool official schema versus the later 17-tool SFT schema.
---

# Tau3 Banking on VMVM

The workflow lives in `user/tianhaowu/tau3_banking_vmvm/`. Run the policy
server as a dedicated H100 job and the evaluator on the CPU partition. Every
conversation executes inside VMVM; model traffic returns through the host-side
authenticated proxy.

## Launch from TOML

Start the policy server:

```bash
policy_job=$(sbatch --parsable \
  user/tianhaowu/tau3_banking_vmvm/run_nemotron_inference_h100.sbatch)
```

Wait for its `/health` endpoint before launching evaluation. Run a one-task
smoke first:

```bash
sbatch --parsable \
  --export=ALL,TAU3_CONFIG=user/tianhaowu/tau3_banking_vmvm/nemotron_super_kimi_smoke.toml,TAU3_OUTPUT_DIR=/checkpoint/ram/$USER/tau3_banking_vmvm/smoke,TAU3_POLICY_JOB_ID="$policy_job",TAU3_LIMIT=1,TAU3_WORKERS=1 \
  user/tianhaowu/tau3_banking_vmvm/run_eval.sbatch
```

Then launch the full 97-task x 5-trial run:

```bash
sbatch --parsable \
  --export=ALL,TAU3_CONFIG=user/tianhaowu/tau3_banking_vmvm/nemotron_super_kimi.toml,TAU3_OUTPUT_DIR=/checkpoint/ram/$USER/tau3_banking_vmvm/nemotron_super_kimi,TAU3_POLICY_JOB_ID="$policy_job",TAU3_WORKERS=16 \
  user/tianhaowu/tau3_banking_vmvm/run_eval.sbatch
```

Validate configuration without contacting providers or leasing VMVMs:

```bash
uv run --frozen python user/tianhaowu/tau3_banking_vmvm/run_eval.py \
  user/tianhaowu/tau3_banking_vmvm/nemotron_super_kimi.toml --dry-run
```

The full denominator is 485: 97 unique tasks and 5 trials. Tau's seed schedule
from base seed 300 is `626729`, `373753`, `361454`, `1567`, and `514337`.

## Required model protocol

Keep the checked-in parity settings unless the requested experiment explicitly
changes them:

- policy: Nemotron 3 Super, temperature 1.0, top-p 0.95, thinking enabled,
  max tokens 32,768, native 262,144-token context;
- user: Kimi K2.6, temperature 0, thinking disabled, max tokens 8,192;
- judge: Kimi K2.6, temperature 0, thinking enabled;
- retrieval: `bm25_grep`;
- limits: 200 Tau steps and 10 tool errors.

Credentials stay on the CPU host. The proxy injects them and logs request
metadata only; never copy provider keys into a VMVM sandbox or result artifact.

## Retry semantics

Keep provider retries inside the individual model call. Retry only transport
errors, HTTP 429, and HTTP 5xx. Treat deterministic HTTP 4xx, context overflow,
empty/length exhaustion, simulation timeout, and other model failures as one
terminal scored zero. Never replay a whole rollout for them.

On a VMVM broken pipe, call `restart_session()` and `recover_last()` so the
in-flight command is collected exactly once. The backend must restore all
registered reverse forwards on the replacement SSH control master before
recovery. Retry the whole unpersisted rollout only when the VM or container is
confirmed lost. Every attempt greater than one must immediately follow a
`vmvm_lost` record for the same `(task_id, trial)`.

Use append-only `results.jsonl`, `attempts.jsonl`, and `proxy_requests.jsonl`.
Do not use Slurm requeue. If the CPU job or node fails, submit the same config
and output directory again; fingerprint validation rejects incompatible resumes
and completed keys are skipped.

For lower-level VMVM diagnosis, also follow `skills/vmvm-runtime/SKILL.md`.

## Monitor and audit

Monitor the Slurm job and append-only counts:

```bash
squeue -j JOB_ID -o '%i %T %M %N %R'
wc -l OUTPUT_DIR/results.jsonl OUTPUT_DIR/attempts.jsonl
tail -n 30 /home/$USER/log/slurm-JOB_ID.err
```

After all 485 rows are present and the job exits successfully, run the full
audit:

```bash
uv run --frozen python user/tianhaowu/tau3_banking_vmvm/audit.py \
  OUTPUT_DIR/results.jsonl --expected-total 485 \
  --summary OUTPUT_DIR/final_audit.json
```

Require `complete`, `coverage_valid`, proxy `protocol_valid`, and
`whole_trial_retry_policy_valid` to be true. Confirm five judge requests, zero
provider retry exhaustions, unique result keys, 97 rows per trial, and no
repeated deterministic provider errors.

Compute standard unbiased pass@k from the five samples per task, not merely the
union of the first k trial indices:

```text
pass@k = mean_task(1 - C(5 - successes_for_task, k) / C(5, k))
```

## Tool-schema scope

The pinned Tau2 v1.0.1 suite exposes 16 initial policy tools under
`bm25_grep`; specialized tools are unlocked dynamically. The later
`sft_v5.0_full_20260820` package records a 17-tool lane by adding
`get_cash_back_disputes_by_user`. Do not silently mix these protocols. The 97
official v1.0.1 task definitions do not reference that extra tool, but its
presence still changes model schema conditioning.

Before reporting a result, record the Tau2 source commit, model snapshot,
semantic config fingerprint, exact numerator/denominator, per-trial passes,
Slurm job IDs, audit path, artifact SHA-256 values, and any protocol caveats in
`user/tianhaowu/tau3_banking_vmvm/RESULTS.md`.
