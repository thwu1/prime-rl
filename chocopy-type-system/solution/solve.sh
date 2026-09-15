#!/bin/bash

# Step 1: Reconstruct hierarchy.json from ELF object file + source
python3 /solution/reconstruct_hierarchy.py

# Step 2: Install the complete type system implementation
cp /solution/chocopy_types_impl.py /app/chocopy_types.py
