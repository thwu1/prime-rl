#!/usr/bin/env bash

set -e

# The solution reverse-engineers both binaries, writes keygens,
# evaluates the cryptographic weakness, finds a collision,
# designs a hardened replacement, and produces a comparative audit.
python3 /solution/reverse_and_build_keygens.py
