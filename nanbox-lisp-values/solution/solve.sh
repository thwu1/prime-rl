#!/bin/bash

set -e

# Install the compact value representation files
cp /solution/value_nanbox.h /app/value.h
cp /solution/value_nanbox.c /app/value.c
cp /solution/lisp_nanbox.c  /app/lisp.c

# 1. Normal build and basic verification
cd /app
make clean all
echo "sizeof(Value) = $(./lisp --sizeof)"
echo "Test: (+ 1 2 3) = $(./lisp --eval '(+ 1 2 3)')"
echo "Test: (type-of 42) = $(./lisp --eval '(type-of 42)')"
echo "Test: (car (list 1 2 3)) = $(./lisp --eval '(car (list 1 2 3))')"

# 2. UBSan build and verification
echo ""
echo "=== UBSan verification ==="
make clean all \
    CFLAGS="-Wall -Wextra -O1 -std=c11 -D_DEFAULT_SOURCE -Wno-unused-parameter -g -fsanitize=undefined -fno-sanitize-recover=all" \
    LDFLAGS="-lm -fsanitize=undefined"
./lisp --eval '(+ 1 2 3)'
./lisp --eval '(car (list 1 2 3))'
./lisp --eval '(/ 1.0 0.0)'
./lisp --eval '(sizeof-value)'
echo "UBSan: PASS"

# 3. Valgrind verification (rebuild without sanitizers)
echo ""
echo "=== Valgrind verification ==="
make clean all
valgrind --error-exitcode=42 --leak-check=no --errors-for-leak-kinds=none \
    ./lisp --eval '(let ((xs (list 1 2 3))) (+ (car xs) (length xs)))'
echo "Valgrind: PASS"

# 4. pahole struct layout report (rebuild with debug info)
echo ""
echo "=== pahole report ==="
make clean all CFLAGS="-Wall -Wextra -O2 -std=c11 -D_DEFAULT_SOURCE -Wno-unused-parameter -g" LDFLAGS="-lm"
pahole ./lisp > /app/size_report.txt 2>&1
echo "pahole report written to /app/size_report.txt"
cat /app/size_report.txt

# 5. Final normal build
make clean all
echo ""
echo "All checks passed."
