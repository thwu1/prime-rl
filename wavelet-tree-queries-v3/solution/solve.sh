#!/bin/bash

# Replace the buggy/incomplete wavelet_tree.hpp with the correct implementation
cp /solution/wavelet_tree_fixed.hpp /app/src/wavelet_tree.hpp

cd /app && make
