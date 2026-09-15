#!/bin/bash

cd /app

# -------------------------------------------------------
# Step 1: Build the Coq project
# -------------------------------------------------------
BUILD_OK=0
if [ -f Makefile ]; then
  make -j1 2>&1 && BUILD_OK=1
elif [ -f _CoqProject ]; then
  coq_makefile -f _CoqProject -o Makefile 2>&1
  make -j1 2>&1 && BUILD_OK=1
else
  # Fallback: compile files individually
  coqc -R . VCC Syntax.v 2>&1 &&  coqc -R . VCC Semantics.v 2>&1 &&  coqc -R . VCC StackMachine.v 2>&1 &&  coqc -R . VCC Compiler.v 2>&1 &&  coqc -R . VCC Optimizer.v 2>&1 &&  coqc -R . VCC Tests.v 2>&1 && BUILD_OK=1
fi
echo "BUILD_OK=$BUILD_OK"

# -------------------------------------------------------
# Step 2: Run independent verification tests
# -------------------------------------------------------
VERIFY_OK=0
cp /tests/verify_tests.v /app/Verify.v

# Extract coq flags from _CoqProject if available
if [ -f _CoqProject ]; then
  COQ_FLAGS=$(grep -E '^-[RQ]' _CoqProject | tr '\n' ' ')
else
  COQ_FLAGS="-R . VCC"
fi
coqc $COQ_FLAGS Verify.v 2>&1 && VERIFY_OK=1
echo "VERIFY_OK=$VERIFY_OK"

# -------------------------------------------------------
# Step 3: Check for Admitted proofs in source files
# -------------------------------------------------------
ADMITTED_COUNT=0
for f in Syntax.v Semantics.v StackMachine.v Compiler.v Optimizer.v; do
  if [ -f "/app/$f" ]; then
    c=$(grep -cw "Admitted" "/app/$f" 2>/dev/null || echo 0)
    ADMITTED_COUNT=$((ADMITTED_COUNT + c))
  fi
done
echo "ADMITTED_COUNT=$ADMITTED_COUNT"

# -------------------------------------------------------
# Step 4: Check for unauthorized axioms
# -------------------------------------------------------
AXIOM_COUNT=0
for f in Syntax.v Semantics.v StackMachine.v Compiler.v Optimizer.v; do
  if [ -f "/app/$f" ]; then
    c=$(grep -cE '^\s*(Axiom|Parameter|Conjecture)\b' "/app/$f" 2>/dev/null || echo 0)
    AXIOM_COUNT=$((AXIOM_COUNT + c))
  fi
done
echo "AXIOM_COUNT=$AXIOM_COUNT"

# -------------------------------------------------------
# Write results for pytest
# -------------------------------------------------------
cat > /tmp/build_results.txt << RESULTS_END
BUILD_OK=$BUILD_OK
VERIFY_OK=$VERIFY_OK
ADMITTED_COUNT=$ADMITTED_COUNT
AXIOM_COUNT=$AXIOM_COUNT
RESULTS_END

# -------------------------------------------------------
# Run pytest and write reward
# -------------------------------------------------------
pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi

exit $exit_code
