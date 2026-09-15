`/app/profiler.py` attempts to produce a roofline performance analysis of the neural network in `/app/model.py` against the hardware specs in `/app/hardware_spec.json`. The profiler's results are wrong — `/app/diagnostic_log.txt` shows its output alongside manually computed reference values. The FLOP counts are off by orders of magnitude, all arithmetic intensity values are suspiciously identical, and the profiler misclassifies every layer's bottleneck type.

Diagnose the fundamental flaws in the existing profiler's instrumentation approach and computational methodology. Then build a correct replacement at `/app/roofline_analyzer.py` that intercepts the actual computational operations occurring during model inference — not just module boundaries — to produce accurate per-operation and per-module roofline metrics including memory alignment analysis.

**`RooflineAnalyzer` interface:**

- `RooflineAnalyzer(hardware_spec: dict, model: nn.Module = None)`
- Context manager wrapping inference: `with analyzer: output = model(input)`
- `get_report()` → analysis dict conforming to `/app/report_schema.json`
- `remove_hooks()` → cleans up registered hooks