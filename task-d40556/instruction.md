NIST's SCTK (Speech Recognition Scoring Toolkit) is installed at `/usr/local/bin/`. The `/app/data/` directory contains speech recognition evaluation data: a reference transcript and hypothesis outputs from 5 ASR systems (`sys1` through `sys5`) with word-level confidence scores.

A colleague began evaluating these systems but abandoned their attempt due to persistent tool errors. Their incomplete, broken work is in `/app/workspace/`. Investigate the data, diagnose the issues in the failed evaluation attempt, and produce a complete and correct evaluation.

Write all result files to `/app/results/`.

## Required outputs

**`individual_wer.csv`** — Word Error Rate for each system. One line per system, all 5 systems present. Format: `system_name,wer_percent` (percentage to one decimal place).

**`nce_scores.csv`** — Normalized Cross Entropy for each system, derived from their word-level confidence scores. One line per system, all 5 systems present. Format: `system_name,nce_value` (NCE to three decimal places).

**`best_rover_combination.txt`** — The 3-system subset (from all C(5,3)=10 possible combinations) achieving the lowest WER when combined via ROVER with average-confidence voting. Single line: comma-separated system names, sorted numerically (e.g., `sys1,sys3,sys4`).

**`best_rover_wer.txt`** — WER (percentage, one decimal) of that optimal 3-system combination.

**`voting_comparison.csv`** — For the optimal 3-system combination, compare three ROVER voting strategies. One line per method, format: `method,wer_percent` (percentage to one decimal place). The three methods, using these exact names: `avgconf`, `maxconf`, `word_frequency`.

**`category_wer.csv`** — Per-label-category WER for the best individual system (lowest overall WER). The reference transcript defines labeled segment categories with IDs `O`, `M`, `F`, `CL`, and `NS`. One line per category, format: `category_id,wer_percent` (percentage to one decimal place).