#!/usr/bin/env bash

set -e

cp /solution/hashmap_impl.c /app/hashmap.c
cd /app
make clean
make
./hashmap_test
