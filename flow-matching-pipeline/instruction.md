`/app/pipeline.py` implements a multi-view video generation pipeline using flow-matching denoising with autoregressive chunked rollout. It was ported from a research codebase and contains multiple numerical and algorithmic errors across its components (scheduler, embeddings, normalization, chunk planning, noise seeding).

`/app/validate.py` runs diagnostics comparing each component's output against known-correct reference values. `/app/mock_model.py` provides a deterministic mock denoiser for testing without GPU resources.

Fix all errors in `/app/pipeline.py` so every diagnostic check in `/app/validate.py` passes. Do not rename classes or change method signatures.