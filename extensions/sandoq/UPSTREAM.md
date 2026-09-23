# Vendored Sandoq extension

This directory vendors `extensions/sandoq` from
`fairinternal/ram_prime_rl` commit
`4890302104d76220cef791c86d2009168597d35f`.

- Upstream repository tree: `33f092a3982916660e12f472588e6ce34a906fc2`
- Upstream subtree: `10b5bd9bbc76eba1b8253637e1869d6b63b7fc42`
- Reviewed vendored tracked-inventory SHA-256 (excluding this metadata file):
  `a5f4868eaf1f6ce678796fe9479fc0ee8d3fa103eabcbe36e576b99d0de16e02`
- Sandoq client pin:
  `0.4.0.2026.8.20.58304.0+hga81e4ca4d312`

Runtime launchers must put this directory on `PYTHONPATH`; its
`sitecustomize.py` installs the SDK-backed `sandoq_provider` implementation.
The Prime-RL tree and reviewed inventory above additionally bind local
background-program cancellation, timeout hardening, and buffered chat capture
layered on that upstream base.
