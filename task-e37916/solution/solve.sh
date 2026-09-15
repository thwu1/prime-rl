#!/bin/bash

set -e

# Copy C source to the build directory
cp /solution/xv6_fsck.c /app/xv6-fsck.c

# Add the missing build rule to the Makefile
cat >> /app/Makefile << 'EOF'

$(TARGET): xv6-fsck.c fs_spec.h
	$(CC) $(CFLAGS) -o $@ xv6-fsck.c $(LDFLAGS)
EOF

# Build the binary
cd /app && make

# Verify the binary works on the reference image
./xv6-fsck reference.img
