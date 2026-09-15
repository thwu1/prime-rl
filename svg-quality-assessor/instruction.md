An SVG quality evaluation pipeline at `/app/pipeline/` processes SVG pairs from `/app/dataset/pairs.json`, rasterizes them via CairoSVG, computes visual fidelity metrics (MSE, SSIM, color histogram distance), derives a composite quality score, and produces a structured report.

The pipeline has multiple defects spanning rasterization configuration, metric computation, color analysis, and quality scoring. Some defects interact — a rendering parameter error propagates through all downstream metrics, multiple independent errors compound within individual modules, and the composite quality model has structural errors in how it combines metric inputs. Certain bugs produce outputs that appear plausible for some input pairs but diverge from correct behavior under closer analysis.

The evaluation methodology at `/app/spec/methodology.md` specifies the theoretical framework, design rationale, and mathematical formulations for each pipeline component. The output JSON schema is at `/app/spec/output_schema.json`.

There is no reference output. Derive correctness from the methodology specification, image quality metric theory, and invariant reasoning about metric properties.

Diagnose and fix all defects across the pipeline modules and produce corrected output at `/app/output/results.json`.