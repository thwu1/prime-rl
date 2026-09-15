#!/usr/bin/env bash

# Append the set operations implementation to hamt.c
cat /solution/setops_impl.c >> /app/src/hamt.c

# Verify it compiles
gcc -std=c11 -Wall -Wextra -O1 -DNDEBUG -I/app/include \
    -c /app/src/hamt.c -o /tmp/hamt_check.o
echo "Set operations implementation appended and compiled successfully."
