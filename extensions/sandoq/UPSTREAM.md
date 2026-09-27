# Vendored Sandoq extension

This directory vendors `extensions/sandoq` from
`fairinternal/ram_prime_rl` commit
`4890302104d76220cef791c86d2009168597d35f`.

- Upstream repository tree: `33f092a3982916660e12f472588e6ce34a906fc2`
- Upstream subtree: `10b5bd9bbc76eba1b8253637e1869d6b63b7fc42`
- Local provenance: `patched-upstream-subtree`. The files retain the upstream
  base above plus reviewed Prime-RL transport, timeout, cancellation, capture,
  and exact-once logical-retry patches.
- Reviewed patched-vendor tracked-inventory SHA-256 (excluding this metadata
  file):
  `b91da5ab8fb09b6b99407e5354ca9330ddfc8f372fad0581e922da4b87bc83b2`
- Sandoq client compatibility pin:
  `1.0.0.2026.9.23.82068.0+hg1a1d394e50c5`. This local dependency update is
  required for the gateway's HTTP-202 Firecracker provisioning flow; the
  vendored provider source remains based on the upstream revision above.

Runtime launchers must put this directory on `PYTHONPATH`; its
`sitecustomize.py` installs the SDK-backed `sandoq_provider` implementation.
The Prime-RL revision and reviewed patched-vendor inventory jointly bind every
local delta layered on the upstream base; the upstream identifiers alone never
assert byte-for-byte equality with the vendored directory.
