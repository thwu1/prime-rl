# RSCI experiment configs

Configs are grouped by workflow so experiment variants do not accumulate in the RSCI root:

- `inference/`: reusable prime-rl inference server configs.
- `eval/`: model, dataset, decoding, and output settings consumed by `scripts/run_eval.sh`.
- `sft/`: supervised fine-tuning variants.
- `rl/`: reinforcement-learning and iterative-frontier variants.

Use descriptive filenames that identify the starting checkpoint, data range, and important treatment. Keep stable shared settings in a base config and use separate files for experimental variants.

The current base-model smoke evaluation is launched with:

```bash
sbatch user/tianhaowu/rsci/scripts/run_eval.sbatch \
  user/tianhaowu/rsci/configs/eval/context_pretrain_id_op2_10_smoke10.toml
```

The Interplay tokenizer represents `<question>`, `<solution>`, and `<answer>` as special tokens. Eval configs must set `skip_special_tokens = false`; otherwise vLLM removes the answer delimiter before strict answer parsing.

The `figure3_*` configs are intentionally explicit: each launched job
snapshots the exact eval TOML and the fully resolved prime-rl inference TOML
under its result directory. Figure 3 uses the released composition checkpoint,
not the context-pretraining checkpoint used by the 10-row smoke test.

The SFT checkpoint configs cover steps 62, 124, 186, and 248 on both Figure 3
panels. `scripts/run_sft_checkpoint_evals.sh` checks each checkpoint's `STABLE`
marker before submitting the corresponding eight-GPU evaluations.
