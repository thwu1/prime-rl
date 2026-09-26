# Vendored Sandoq extension

This directory vendors `extensions/sandoq` from
`fairinternal/ram_prime_rl` commit
`4890302104d76220cef791c86d2009168597d35f`.

- Upstream repository tree: `33f092a3982916660e12f472588e6ce34a906fc2`
- Upstream subtree: `10b5bd9bbc76eba1b8253637e1869d6b63b7fc42`
- Reviewed tracked-inventory SHA-256 (excluding this metadata file):
  `9d3a1b4d4898659b6fff4d81efcec557286b94de4c9dd933cd8b4ea543ffe4ea`
- Sandoq client compatibility pin:
  `1.0.0.2026.9.23.82068.0+hg1a1d394e50c5`. This local dependency update is
  required for the gateway's HTTP-202 Firecracker provisioning flow; the
  vendored provider source remains based on the upstream revision above.

Runtime launchers must put this directory on `PYTHONPATH`; its
`sitecustomize.py` installs the SDK-backed `sandoq_provider` implementation.
The Prime-RL tree and reviewed inventory above additionally bind local
background-program cancellation, timeout hardening, and buffered chat capture
layered on that upstream base.
