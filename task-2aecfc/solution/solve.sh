#!/usr/bin/env bash

set -e

pip3 install pyyaml==6.0.2 -q

python3 /solution/solve_engine.py
