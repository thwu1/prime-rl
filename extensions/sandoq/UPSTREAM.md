# Vendored Sandoq extension

This directory vendors `extensions/sandoq` from
`fairinternal/ram_prime_rl` commit
`4890302104d76220cef791c86d2009168597d35f`.

- Upstream repository tree: `33f092a3982916660e12f472588e6ce34a906fc2`
- Upstream subtree: `10b5bd9bbc76eba1b8253637e1869d6b63b7fc42`
- Upstream tracked-inventory SHA-256:
  `5db69d90ddd34cfbfdcffdacab09353e8be22e917f894e33ddafb5020ca43e73`
- Sandoq client pin:
  `0.4.0.2026.8.20.58304.0+hga81e4ca4d312`

Runtime launchers must put this directory on `PYTHONPATH`; its
`sitecustomize.py` installs the SDK-backed `sandoq_provider` implementation.
