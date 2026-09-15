#!/bin/bash

set -e

# Copy the correct implementations
cp /solution/avl_impl.cpp /app/src/avl.cpp
cp /solution/zset_impl.cpp /app/src/zset.cpp
cp /solution/heap_impl.cpp /app/src/heap.cpp

# Rebuild
make -C /app/src clean
make -C /app/src
