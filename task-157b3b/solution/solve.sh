#!/bin/bash

# Implement the complete lock-free MPMC queue system
python3 /solution/implement_queue.py

# Verify the implementation compiles and passes stress test
cd /app
g++ -std=c++17 -O2 -pthread -o stress_test stress_test.cpp
./stress_test

# Verify TSan clean
g++ -std=c++17 -O1 -g -fsanitize=thread -pthread -DITEMS_PER_PRODUCER=2000 -o stress_test_tsan stress_test.cpp
TSAN_OPTIONS=halt_on_error=1 ./stress_test_tsan

echo "All tests passed."
