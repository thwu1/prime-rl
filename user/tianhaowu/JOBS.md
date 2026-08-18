# Job ledger — terminal-bench eval on Qwen3.5-35B-A3B (prime-rl + VMVM/vacli)

Model: /checkpoint/ram/tianhaowu/Qwen3.5-35B-A3B  ·  Task set: v2_harbor_pass80.jsonl (canonical 80)
Env: vmvm-tb (verifiers MultiTurnEnv, native <tool_call>, model-outside no-egress, VMVM via vacli)

| job id  | date (PDT)   | config                 | script                    | params            | purpose / result |
|---------|--------------|------------------------|---------------------------|-------------------|------------------|
| 8232147 | 2026-06-15   | qwen35_infer.toml      | qwen35_serve_smoke.sbatch | tp=8              | serve smoke; FlashInfer GDN prefill JIT hang -> set gdn_prefill_backend=triton |
| 8232406 | 2026-06-15   | qwen35_infer.toml      | qwen35_serve_smoke.sbatch | tp=8, triton      | serve OK after 1-time CUTLASS MoE compile (~790s, cached). Real completion. |
| 8233181 | 2026-06-16   | qwen35_infer.toml      | vmvm_tb_eval_smoke.sbatch | n=1               | E2E 1-task; works but SLOW (enforce_eager, 16 tok/s) |
| 8233417 | 2026-06-16   | qwen35_infer_fast.toml | (fast)                    | n=4 conc=4        | fast config: 182-363 tok/s (CUDA graphs). terminus2 fmt -> parse-error fails |
| 8233778 | 2026-06-16   | qwen35_infer_fast.toml | vmvm_tb_eval_full.sbatch  | n=4 conc=4        | native <tool_call> fmt validated (72-turn submit, 200-turn maxturn) |
| 8234074 | 2026-06-16   | qwen35_infer_fast.toml | vmvm_tb_eval_full.sbatch  | n=86 conc=12      | FULL single-shot pass@1 = 20/80 = 25% (first ~65 tasks 30-33%; hard tail dragged) |
| 8236098 | 2026-06-16   | qwen35_infer_fast.toml | vmvm_tb_eval_pass2.sbatch | rollouts=2 conc=12| pass@2 over 80, raised limits (max_turns=300, timeouts=420). RUNNING. |

Notes:
- qwen35_infer_fast.toml updated 2026-06-16 to max_model_len=262144 (native 256K; hybrid linear-attn => small KV).
- pass@2 sbatch & full sbatch now pass --state-columns turn_timings (per-turn exec_s/gen_s/gen_tokens persisted).
- env committed: prime-rl @ 0829fba6c "feat(env): vmvm-tb terminal-bench eval environment".
