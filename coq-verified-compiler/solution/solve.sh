#!/bin/bash

set -e

cd /app

# -------------------------------------------------------
# Fix 1: _CoqProject
#   - Change -Q to -R (so bare Require Import works)
#   - Change Extraction.v to Tests.v (correct filename)
# -------------------------------------------------------
cp /solution/CoqProject_fixed _CoqProject

# -------------------------------------------------------
# Fix 2: StackMachine.v
#   - ISub: change (a - b) to (b - a) for correct operand order
#   - Complete the exec_app proof
# -------------------------------------------------------
cp /solution/StackMachine_fixed.v StackMachine.v

# -------------------------------------------------------
# Fix 3: Compiler.v
#   - Complete the compile_correct proof
# -------------------------------------------------------
cp /solution/Compiler_fixed.v Compiler.v

# -------------------------------------------------------
# Fix 4: Optimizer.v
#   - In Minus branch: change (n1 + n2) to (n1 - n2)
#   - Complete the optimize_correct proof
# -------------------------------------------------------
cp /solution/Optimizer_fixed.v Optimizer.v

# -------------------------------------------------------
# Build the project
# -------------------------------------------------------
coq_makefile -f _CoqProject -o Makefile
make -j1
