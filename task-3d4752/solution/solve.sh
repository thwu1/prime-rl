#!/bin/bash

# Deploy the solution implementation
cp /solution/hsm_impl.c /app/hsm.c

# Build and verify all test suites
echo "=== Primary suite (10 tests) ==="
gcc -Wall -Wextra -std=c11 -o /app/hsm_test /app/main.c /app/hsm.c /app/test_sm.c
/app/hsm_test

echo ""
echo "=== Secondary suite (6 tests) ==="
gcc -Wall -Wextra -std=c11 -o /app/hsm_test2 /tests/test_main2.c /tests/test_sm2.c /app/hsm.c -I/app
/app/hsm_test2

echo ""
echo "=== Guard suite (8 tests) ==="
gcc -Wall -Wextra -std=c11 -o /app/hsm_test3 /tests/test_main3.c /tests/test_sm3.c /app/hsm.c -I/app
/app/hsm_test3

echo ""
echo "=== State containment query suite ==="
gcc -Wall -Wextra -std=c11 -o /app/hsm_test_isin /tests/test_is_in.c /app/hsm.c /app/test_sm.c -I/app
/app/hsm_test_isin

echo ""
echo "=== Valgrind memcheck ==="
gcc -Wall -Wextra -std=c11 -g -o /app/hsm_test_vg /app/main.c /app/hsm.c /app/test_sm.c
valgrind --error-exitcode=42 --leak-check=full --errors-for-leak-kinds=definite /app/hsm_test_vg
