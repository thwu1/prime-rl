#!/bin/bash


cd /app
python3 /solution/build_ext2.py

echo "=== fsck verification ==="
fsck.ext2 -fn /app/ext2.img
