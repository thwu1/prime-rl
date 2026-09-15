#!/bin/bash

# Copy implementation files into place
cp /solution/threads_impl.c /app/threads.c
cp /solution/malloc_impl.c  /app/malloc.c
cp /solution/malloc_impl.h  /app/malloc.h

# Update Makefile to compile new sources
sed -i 's/^SRCS = startup.c os.c uart.c$/SRCS = startup.c os.c uart.c threads.c malloc.c/' /app/Makefile

# Build
cd /app && make clean && make
