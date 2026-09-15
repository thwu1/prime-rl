# Makefile for the fused RoPE C extension library
#
# Goal: compile csrc/rope_fused.c into lib/librope.so
# The shared library must export symbols: rope_apply, rope_apply_batch
#
# Usage:
#   make -C /app build   # compile the shared library
#   make -C /app clean   # remove build artifacts

CC ?= gcc

# TODO: set compiler/linker flags needed to produce a shared library
CFLAGS =

SRCDIR = csrc
LIBDIR = lib

build:
	mkdir -p $(LIBDIR)
	# TODO: compile $(SRCDIR)/rope_fused.c into $(LIBDIR)/librope.so

clean:
	rm -rf $(LIBDIR)

.PHONY: build clean
