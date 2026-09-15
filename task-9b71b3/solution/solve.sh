#!/bin/bash

set -e

export SPACK_ROOT=/opt/spack
export PATH="$SPACK_ROOT/bin:$PATH"

# Create missing packages, complete scilinalg, and configure environment
python3 /solution/create_packages.py

# Concretize the environment
spack -e /app/env concretize --force
