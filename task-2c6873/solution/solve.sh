#!/bin/bash

# Install the toolchain
cp /solution/cpu0asm.py /app/cpu0asm
cp /solution/cpu0ld.py /app/cpu0ld
cp /solution/cpu0sim.py /app/cpu0sim
chmod +x /app/cpu0asm /app/cpu0ld /app/cpu0sim

# Run single-file pipelines to verify computation
/app/cpu0asm /app/programs/arith.s /tmp/arith.o
/app/cpu0ld -o /tmp/arith /tmp/arith.o
/app/cpu0sim /tmp/arith

/app/cpu0asm /app/programs/factorial.s /tmp/factorial.o
/app/cpu0ld -o /tmp/factorial /tmp/factorial.o
/app/cpu0sim /tmp/factorial

/app/cpu0asm /app/programs/gcd.s /tmp/gcd.o
/app/cpu0ld -o /tmp/gcd /tmp/gcd.o
/app/cpu0sim /tmp/gcd

# Run multi-file pipeline
/app/cpu0asm /app/programs/main.s /tmp/main.o
/app/cpu0asm /app/programs/mathlib.s /tmp/mathlib.o
/app/cpu0asm /app/programs/utils.s /tmp/utils.o
/app/cpu0ld -o /tmp/multifile /tmp/main.o /tmp/mathlib.o /tmp/utils.o
/app/cpu0sim /tmp/multifile

exit 0
