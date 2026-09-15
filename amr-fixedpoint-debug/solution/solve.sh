#!/bin/bash

set -euo pipefail

cd /app

# Fix L_mult saturation constant (wrong comparison value)
sed -i 's/0x40000001L/0x40000000L/' basicop.c

# Fix round_fx rounding constant (wrong rounding offset)
sed -i 's/0x00000800L/0x00008000L/' basicop.c

# Fix norm_l normalization threshold (wrong normalization range)
sed -i 's/0x20000000L/0x40000000L/' basicop.c

# Add missing cross-term in Mpy_32 DPF multiplication
sed -i '/L_mac(L_32, mult(hi1, lo2), 1);/a\    L_32 = L_mac(L_32, mult(lo1, hi2), 1);' oper_32b.c

# Replace Levinson stub with correct implementation
cp /solution/levinson_correct.c levinson.c

# Build
make clean
make
