CC = gcc
CFLAGS = -O2 -fPIC

all: libkernels.so

libkernels.so: kernels.c
	$(CC) $(CFLAGS) -shared -o $@ $< -lm

clean:
	rm -f libkernels.so
