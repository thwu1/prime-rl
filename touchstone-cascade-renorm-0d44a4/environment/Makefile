CC = gcc
CFLAGS = -fPIC -O2 -Wall

all: libmatrix.so

libmatrix.so: matrix_ops.c matrix_ops.h
	$(CC) $(CFLAGS) -shared -o $@ matrix_ops.c -lm

clean:
	rm -f libmatrix.so

.PHONY: all clean
