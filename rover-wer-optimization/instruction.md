Four ASR systems have produced transcription hypotheses with word-level confidence scores for a broadcast recording. Reference and hypothesis files are at `/app/data/` (`reference.stm`, `sys1.ctm` through `sys4.ctm`). SCTK is installed system-wide.

Perform a comprehensive evaluation of these systems — individually and in combination — and produce `/app/results/analysis.json`:

```json
{
  "per_system": {
    "sys1": {
      "wer": <float>,
      "nce": <float>,
      "speaker_wer": {"spk1": <float>, "spk2": <float>}
    },
    "sys2": { ... }, "sys3": { ... }, "sys4": { ... }
  },
  "calibration_ranking": ["<best_nce_system>", "<2nd>", "<3rd>", "<worst_nce_system>"],
  "rover_optimization": {
    "best_config": {
      "systems": ["<sysA>", "<sysB>", ...],
      "method": "<string>",
      "alpha": <float>,
      "wer": <float>
    },
    "search_log": [
      {"systems": [...], "method": "<string>", "alpha": <float>, "wer": <float>},
      ...
    ]
  }
}
```

- WER values are percentages (e.g., 15.3 for 15.3%).
- `calibration_ranking` orders systems by confidence calibration quality, best first.
- `best_config` must be globally optimal — no other feasible combination of systems and parameters should achieve lower WER.
- `search_log` records every configuration evaluated during the optimization.