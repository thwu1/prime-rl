#!/bin/bash

cp /solution/walloc_native.c /app/walloc_native.c
cp /solution/walloc_native.h /app/walloc_native.h

cd /app
gcc -shared -fPIC -O2 -DNDEBUG -I/app -o /app/libwalloc.so /app/walloc_native.c
echo "Solution deployed and compiled successfully"
