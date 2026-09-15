CC = gcc
CFLAGS = -O2 -Wall -fPIC

all: libqrng.so

libqrng.so: sobol.c norm_inv.c qrng.h
	$(CC) $(CFLAGS) -c sobol.c -o sobol.o
	$(CC) $(CFLAGS) -c norm_inv.c -o norm_inv.o
	ar rcs libqrng.so sobol.o norm_inv.o

clean:
	rm -f *.o libqrng.so
