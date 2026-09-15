#!/bin/bash

# Install Python dependencies
pip3 install scipy==1.14.1 numpy==2.1.3 -q 2>&1

# Verify scipy installed
python3 -c "import scipy; print('scipy', scipy.__version__, 'OK')" || {
    echo "ERROR: scipy installation failed"
    exit 1
}

# --- Step 1: Compile Fortran RADAU5 solver for E5 ---
echo "Compiling Fortran RADAU5 solver..."
cd /app/fortran
gfortran -std=legacy -O2 -o /app/e5_radau5 \
    /solution/ref_driver.f \
    equation.f \
    radau5.f \
    dc_decsol.f \
    decsol.f 2>&1

if [ $? -ne 0 ]; then
    echo "ERROR: Fortran compilation failed"
    exit 1
fi
echo "Compilation successful."

# --- Step 2: Run Fortran solver and create reference CSV ---
echo "Running Fortran solver..."
cd /app
./e5_radau5 > /tmp/fortran_raw.txt 2>&1
FORTRAN_EXIT=$?

if [ $FORTRAN_EXIT -ne 0 ]; then
    echo "WARNING: Fortran solver exited with code $FORTRAN_EXIT"
fi

echo "Fortran raw output:"
cat /tmp/fortran_raw.txt

python3 -c "
import csv
rows = []
with open('/tmp/fortran_raw.txt') as f:
    for line in f:
        parts = line.split()
        if len(parts) == 5:
            try:
                vals = [float(x.replace('D','E').replace('d','e')) for x in parts]
                rows.append({
                    't': vals[0], 'y1': vals[1],
                    'y2': vals[2], 'y3': vals[3], 'y4': vals[4]
                })
            except ValueError as e:
                print(f'Skipping line: {line.strip()} ({e})')
with open('/app/fortran_reference.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['t','y1','y2','y3','y4'])
    w.writeheader()
    w.writerows(rows)
print(f'Wrote {len(rows)} rows to /app/fortran_reference.csv')
"

if [ ! -f /app/fortran_reference.csv ]; then
    echo "ERROR: Failed to create fortran_reference.csv"
    exit 1
fi

# --- Step 3: Copy and run Python solver ---
echo "Running Python E5 solver..."
cp /solution/e5_solver.py /app/e5_solver.py
python3 /app/e5_solver.py 2>&1
PYTHON_EXIT=$?

if [ $PYTHON_EXIT -ne 0 ]; then
    echo "WARNING: Python solver exited with code $PYTHON_EXIT"
fi

# Verify outputs
echo "--- Output verification ---"
for f in /app/fortran_reference.csv /app/python_results.csv /app/eigenvalues.json /app/e5_solver.py; do
    if [ -f "$f" ]; then
        echo "OK: $f exists"
    else
        echo "MISSING: $f"
    fi
done

echo "All steps completed."
