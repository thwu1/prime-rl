#!/bin/bash

set -e

cp /solution/ed25519_impl.c /app/ed25519.c
cd /app
make clean
make
