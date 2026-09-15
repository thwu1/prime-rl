CC = gcc
CFLAGS = -fPIC -O2
LDFLAGS = -shared

.PHONY: all lib run clean

all: lib run

lib: libmatkernel.so

libmatkernel.so: matrix_kernel.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<

run: lib
	python3 run_analysis.py

clean:
	rm -f libmatkernel.so results.json results.db
