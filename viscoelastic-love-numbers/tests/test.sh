#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 -q

# Compile TABOO reference implementation
TABOO_DIR=$(mktemp -d)
cp /app/taboo.f90 "$TABOO_DIR/"
cd "$TABOO_DIR"

# Sanitize non-ASCII characters that break gfortran string parsing
LC_ALL=C tr -cd '\000-\177' < taboo.f90 > taboo_clean.f90
mv taboo_clean.f90 taboo.f90

echo "Compiling TABOO..."
gfortran -O2 -fallow-argument-mismatch -std=legacy -ffree-line-length-none -w taboo.f90 -o taboo.exe 2>&1 | tail -20
COMPILE_RC=${PIPESTATUS[0]}

if [ ! -f taboo.exe ]; then
    echo "Trying alternate compilation flags..."
    gfortran -O0 -fallow-argument-mismatch -std=legacy -ffree-line-length-none -w taboo.f90 -o taboo.exe 2>&1 | tail -20
fi

if [ ! -f taboo.exe ]; then
    echo "ERROR: TABOO compilation failed"
    mkdir -p /logs/verifier && echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi
echo "TABOO compiled successfully"

# Create TABOO input files for NV=2, CODE=2 (Yuen-Sabadini-Boschi 1982)
cat > task_1.dat << 'TASK1EOF'
Active
Harmonic_Degrees
    2   30
    0
    1
Make_Model
    2
    2
    100.0
    0
    2.0
    1.0
El_Fluid_Viscel
    1
    1
    1
TASK1EOF

cat > task_2.dat << 'TASK2EOF'
!Inactive
TASK2EOF

cat > task_3.dat << 'TASK3EOF'
!Inactive
TASK3EOF

echo "Running TABOO..."
./taboo.exe
TABOO_RC=$?
echo "TABOO exit code: $TABOO_RC"

if [ -f taboo.log ]; then
    echo "=== TABOO log (last 20 lines) ==="
    tail -20 taboo.log
    echo "=== end log ==="
fi

# Copy reference output
mkdir -p /app/taboo_reference
for f in spectrum.dat h.dat l.dat k.dat taboo.log; do
    if [ -f "$f" ]; then
        cp "$f" /app/taboo_reference/
        echo "Copied $f to /app/taboo_reference/"
    else
        echo "WARNING: $f not found in TABOO output"
    fi
done

cd /app

# Verify reference files exist
MISSING=0
for f in spectrum.dat h.dat l.dat k.dat; do
    if [ ! -f "/app/taboo_reference/$f" ]; then
        echo "ERROR: Reference file $f missing"
        MISSING=1
    fi
done

if [ $MISSING -eq 1 ]; then
    echo "TABOO reference generation failed"
    mkdir -p /logs/verifier && echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
RESULT=0
pytest /tests/test_state.py -v || RESULT=1

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $RESULT
