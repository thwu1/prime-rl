#!/usr/bin/env bash

set -e

# Deploy the correct signal tree implementation
cp /solution/signal_tree_impl.c /app/signal_tree.c

# Build
cd /app
make clean
make
