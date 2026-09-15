You are given a mathematical specification for a generalized sigma-parameterized diffusion framework, a working UNet backbone, and a skeleton implementation with empty method stubs.

The framework uses a configurable preconditioning exponent α (default 3) instead of standard quadratic scaling, tanh-compressed noise conditioning, a log-cosine sigma schedule, and a modified DPM++ second-order correction with damped coefficient γ = −1/(2r + r²).

Implement all methods in `/app/diffusion.py` that raise `NotImplementedError`, following the mathematical specification in `/app/spec.md`.

Your implementation must correctly handle:
- All four preconditioning functions using the generalized exponent α
- The preconditioned denoiser forward pass with proper sigma broadcasting
- The log-cosine sigma sampling schedule
- Training with log-normal noise sampling, per-sample loss weighting, and optional self-conditioning
- The stochastic Heun (second-order) sampler with configurable noise injection
- The modified DPM++ second-order multistep sampler with damped correction

Key files:
- `/app/spec.md` — Mathematical specification
- `/app/unet.py` — UNet backbone (do not modify)
- `/app/helpers.py` — Utility functions (do not modify)
- `/app/diffusion.py` — Skeleton to complete