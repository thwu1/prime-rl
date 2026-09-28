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
  `78f35c58e7474e087e9653b90d563cf4eb00030f509e4baca42866b1cded7905`
- Reviewed bounded-upload overlay: base Prime-RL revision
  `aa3ebebec140261a437f538ffcb8b9b913974057`, effective revision
  `eee438556236abb5e186621bdda15e6141763590`. Its complete Sandoq delta is:
  - `extensions/sandoq/sandoq_provider/oci_client.py`: blob
    `11b6c7c4b669d58cebde34535c718c224992cc17` ->
    `5739b390ead61cf5eb492bece557a086c1b8ad91`
  - `extensions/sandoq/sandoq_provider/tests/test_oci_client_security.py`: blob
    `63fdddb48844d778ccca8831c02f28b172cfbb2e` ->
    `e29210dc47a3a4ad6c59fabee75c2ffe21b189f8`
- Sandoq client compatibility pin:
  `1.0.0.2026.9.23.82068.0+hg1a1d394e50c5`. This local dependency update is
  required for the gateway's HTTP-202 Firecracker provisioning flow; the
  vendored provider source remains based on the upstream revision above.

Runtime launchers must put this directory on `PYTHONPATH`; its
`sitecustomize.py` installs the SDK-backed `sandoq_provider` implementation.
The Prime-RL revision and reviewed patched-vendor inventory jointly bind every
local delta layered on the upstream base; the upstream identifiers alone never
assert byte-for-byte equality with the vendored directory.
