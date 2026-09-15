CC = gcc
CFLAGS = -O2 -Wall -fPIC

all: libdual.so

libdual.so: dual.c dual.h
	$(CC) $(CFLAGS) -shared -o libdual.so dual.c -lm

clean:
	rm -f *.so
