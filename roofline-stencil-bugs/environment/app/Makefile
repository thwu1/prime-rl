CC = gcc
CFLAGS = -O2 -Wall

all: kernels/stencil_kernel.so

kernels/stencil_kernel.so: kernels/stencil_kernel.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f kernels/*.so kernels/*.o

.PHONY: all clean
