#!/bin/bash

# Copy the complete solution to /app/main.cpp
cp /solution/main_solved.cpp /app/main.cpp

# Restore test data from backup if missing
if [ ! -d /app/tests ]; then
    cp -r /opt/initial_app/tests /app/tests
fi

# Compile
cd /app
rm -f solution
g++ -O2 -std=c++17 -Wall -o solution main.cpp
if [ $? -ne 0 ]; then
    echo "Compilation failed"
    exit 1
fi

# Verify all test cases
all_pass=true
for i in 1 2 3; do
    actual=$(./solution < /app/tests/input${i}.txt)
    expected=$(cat /app/tests/expected${i}.txt | tr -d '\r')
    actual_clean=$(echo "$actual" | tr -d '\r')
    if [ "$actual_clean" = "$expected" ]; then
        echo "Test $i: PASS"
    else
        echo "Test $i: FAIL"
        echo "  Expected: $expected"
        echo "  Got:      $actual_clean"
        all_pass=false
    fi
done

if [ "$all_pass" = true ]; then
    echo "All tests passed"
else
    echo "Some tests failed"
    exit 1
fi
