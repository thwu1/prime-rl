# user/tianhaowu — reproducibility folder

Every eval/serve job we launch is captured here.

- `configs/` — vLLM serving configs (prime-rl `inference @ <toml>`)
- `scripts/` — sbatch launch scripts + analysis helpers
- `JOBS.md`  — ledger of every SLURM job (id, config, script, purpose, result)

## How to reproduce a terminal-bench eval (Qwen3.5-35B-A3B)

```bash
cd ~/prime-rl
# pass@1 over canonical 80:
sbatch --export=ALL,VMVM_N=80,VMVM_CONC=12 user/tianhaowu/scripts/vmvm_tb_eval_full.sbatch
# pass@2 (each task 2 samples, solved if either passes), raised limits:
sbatch --export=ALL,VMVM_CONC=12 user/tianhaowu/scripts/vmvm_tb_eval_pass2.sbatch
```

Each sbatch: serves Qwen3.5 via `inference @ configs/qwen35_infer_fast.toml` (tp=8,
language_model_only, gdn_prefill_backend=triton, prefix-caching, CUDA graphs, 256K ctx),
waits for `:8000` ready, then runs `vf-eval vmvm-tb` against it with
`--state-columns turn_timings` (per-turn exec_s/gen_s/gen_tokens saved).

Score: `python scripts/poll_pass1.py` (pass@1) or `scripts/poll_pass2.py` (pass@2).
Visualize: `python scripts/make_vmvm_tb_viewer.py [results.jsonl] [out.html]`.
