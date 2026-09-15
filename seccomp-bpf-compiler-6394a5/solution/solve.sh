#!/bin/bash


# Fix all bugs in bpf_compiler.c by replacing it with the corrected version,
# then rebuild the compiler and regenerate the filter.

set -e

cd /app

cp /solution/bpf_compiler_fixed.c /app/bpf_compiler.c

make clean
make bpf_compiler
make filter.bpf
