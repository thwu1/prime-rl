# Differential Flame Graph Analysis

Generated on 2024-11-19 by Alex Chen.

## Commands used

```bash
cd /app

# Generate differential folded stacks
perl FlameGraph/difffolded.pl profiles/incident.folded profiles/baseline.folded > analysis/diff.folded

# Generate differential flame graph SVG
perl FlameGraph/flamegraph.pl --negate < analysis/diff.folded > analysis/diff.svg
```

## Interpretation

- Red = regression (more samples in second file)
- Blue = improvement (fewer samples in second file)

See `engineer_report.md` for full analysis.
