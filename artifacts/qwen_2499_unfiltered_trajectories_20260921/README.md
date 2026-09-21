# Qwen 2,499-task unfiltered trajectories

This bundle contains the original, unexpanded rollout records for the Qwen
2.4T run. It includes positive-reward, zero-reward, and error outcomes. The
VMVM source also retains 126 superseded retry records, so the two files contain
2,625 JSONL records while covering 2,499 distinct canonical tasks.

The payloads are compressed byte-for-byte source snapshots. They have not been
filtered, rendered into SFT rows, or otherwise transformed. They contain raw
task and model-I/O payloads; avoid rendering their contents in logs or review
tools.

## Size

- Original JSONL: 2,183,550,892 bytes
- Compressed chunks: 154,413,416 bytes
- Reduction: 92.93% (14.13x smaller)
- Largest chunk: 50,331,648 bytes (48 MiB)

## Verify and reconstruct

Run from this directory:

```bash
sha256sum --check SHA256SUMS

cat qwen_vmvm_epoch3_results.jsonl.zst.part-* \
  > qwen_vmvm_epoch3_results.jsonl.zst
cat qwen_sandoq_continuation_results.jsonl.zst.part-* \
  > qwen_sandoq_continuation_results.jsonl.zst

zstd -d --long=31 qwen_vmvm_epoch3_results.jsonl.zst
zstd -d --long=31 qwen_sandoq_continuation_results.jsonl.zst

sha256sum qwen_vmvm_epoch3_results.jsonl \
  qwen_sandoq_continuation_results.jsonl
```

The expected source-file and reconstructed-stream digests are recorded in
`manifest.json`.
