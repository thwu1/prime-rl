#!/bin/bash

# Fix the buggy LZ4 block compressor/decompressor and add analyze command.
# Six bugs to fix in lz4_block.c:
#   1. Compressor match finder: memcmp uses 3 instead of MINMATCH (4)
#   2. Compressor offset: big-endian instead of little-endian
#   3. Compressor match length: stores match_len, not match_len - MINMATCH
#   4. Decompressor offset: big-endian instead of little-endian
#   5. Decompressor match length: reads raw value, doesn't add MINMATCH
#   6. Decompressor match copy: memcpy fails on overlapping matches
# Plus: implement the analyze command in main.c

cp /solution/lz4_block_fixed.c /app/lz4_block.c
cp /solution/main_fixed.c /app/main.c
cd /app && make clean && make
