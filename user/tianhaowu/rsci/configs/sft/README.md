# SFT configs

`figure3_op11_14_200k_1epoch.toml` is the main one-off SFT treatment. It uses
the released Figure 3 base checkpoint, all 200K held-out op11-14 gold
solutions, the paper's 512K-token global batch, learning rate, weight decay,
and cosine floor. The data manifest simulates prime-rl's shuffled data-parallel
packing and resolves one epoch to 248 optimizer updates. Loss is applied only
to the solution and answer. The 200-step config is a fixed-update ablation.

Run the one-step config first whenever the model or prime-rl revision changes.
All configs launch through `scripts/run_sft.sh`, which delegates to
`uv run sft`, writes the resolved config and generated SLURM script beneath the
configured output directory, and forwards CLI overrides. They select the RSCI
offline template so compute jobs use the already-synchronized project
environment without attempting unrelated dependency downloads.
