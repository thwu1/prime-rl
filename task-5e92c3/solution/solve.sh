#!/bin/bash

# Deploy the compiler
cp /solution/compiler.py /app/compiler.py

# Compile and verify each test program
declare -A EXPECTED
EXPECTED[test01_return]=42
EXPECTED[test02_arith]=42
EXPECTED[test03_chain]=49
EXPECTED[test04_call]=42
EXPECTED[test05_branch]=42
EXPECTED[test06_memory]=42
EXPECTED[test07_loop]=55
EXPECTED[test08_global]=155
EXPECTED[test09_factorial]=120
EXPECTED[test10_array]=60
EXPECTED[test11_bitwise]=159
EXPECTED[test12_six_args]=21
EXPECTED[test13_eight_args]=36
EXPECTED[test14_cmp_ops]=4
EXPECTED[test15_fib_print]=55

mkdir -p /tmp/ll_build

FAIL=0
for name in "${!EXPECTED[@]}"; do
    python3 /app/compiler.py "/app/tests/${name}.ll" -o "/tmp/ll_build/${name}.s" 2>&1
    if [ $? -ne 0 ]; then
        echo "COMPILE FAIL: $name"
        FAIL=1
        continue
    fi

    gcc -o "/tmp/ll_build/${name}" "/tmp/ll_build/${name}.s" /app/runtime.c -no-pie 2>&1
    if [ $? -ne 0 ]; then
        echo "LINK FAIL: $name"
        FAIL=1
        continue
    fi

    "/tmp/ll_build/${name}"
    actual=$?
    expected=${EXPECTED[$name]}
    if [ "$actual" -ne "$expected" ]; then
        echo "FAIL: $name expected=$expected got=$actual"
        FAIL=1
    else
        echo "PASS: $name ($actual)"
    fi
done

if [ $FAIL -ne 0 ]; then
    echo "Some tests failed."
    exit 1
fi
echo "All tests passed."
