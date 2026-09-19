#!/usr/bin/env python3
"""Run the stdlib-only source-wheel execution-binding inspector."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    bootstrap = Path(__file__).resolve(strict=True).with_name("source_wheel_proof_bootstrap.py")
    sys.argv = [str(bootstrap), "inspect", *sys.argv[1:]]
    runpy.run_path(str(bootstrap), run_name="__main__")


if __name__ == "__main__":
    main()
