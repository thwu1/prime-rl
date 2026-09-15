#!/bin/bash

set -eo pipefail

cd /app

python3 -m venv .venv
. /app/.venv/bin/activate

pip3 install maturin==1.7.8 -q

cp /solution/fixed_lib.rs /app/src/lib.rs

maturin develop
