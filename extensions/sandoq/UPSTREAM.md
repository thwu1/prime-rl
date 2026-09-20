# Vendored Sandoq extension

This directory vendors `extensions/sandoq` from
`fairinternal/ram_prime_rl` commit
`f7313db42eea4b3be8bcbe16a8072f73cf6abed5`.

- Upstream subtree: `46ee7064345aa0e8cee47b61a21feeb2d9049361`
- Upstream tracked-inventory SHA-256:
  `9fe562f29c37aefb32ce6bf8ad79270434d6ccc6c94f6b044ec72e7e377e1439`
- Sandoq client pin:
  `0.4.0.2026.8.20.58304.0+hga81e4ca4d312`

Runtime launchers must put this directory on `PYTHONPATH`; its
`sitecustomize.py` installs the SDK-backed `sandoq_provider` implementation.
