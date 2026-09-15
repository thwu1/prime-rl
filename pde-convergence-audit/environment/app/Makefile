CC = gcc
CFLAGS = -O2 -Wall -std=c11

SRCDIR = kernels
TARGET = libpde_kernels.so

all: $(TARGET)

$(TARGET): $(SRCDIR)/stencils.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(TARGET)

.PHONY: all clean
