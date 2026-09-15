#!/bin/bash

cp /solution/hashtable_impl.c /app/hashtable.c
gcc -shared -fPIC -O2 -fvisibility=hidden -o /app/libhashtable.so /app/hashtable.c
