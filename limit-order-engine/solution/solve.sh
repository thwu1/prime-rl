#!/bin/bash

# Copy solution source files
cp /solution/engine_lib.c /app/engine_lib.c
cp /solution/engine_main.c /app/engine_main.c

# Write Makefile for shared library + CLI binary
cat > /app/Makefile << 'MKEOF'
CC = gcc
CFLAGS = -O2 -Wall -Wextra -std=c11 -Iinclude -fPIC -fvisibility=hidden
LDFLAGS = -lm

all: libengine.so engine

libengine.so: engine_lib.o
	$(CC) -shared -o $@ $^ $(LDFLAGS)

engine: engine_main.o libengine.so
	$(CC) $(CFLAGS) -o $@ engine_main.o -L. -lengine -Wl,-rpath,/app $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f engine libengine.so *.o

.PHONY: all clean
MKEOF

make -C /app
