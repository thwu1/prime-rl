CC = gcc
CFLAGS = -O2 -Wall

all: libntt.so

libntt.so: ntt.c ntt.h
	$(CC) $(CFLAGS) -o $@ ntt.c

clean:
	rm -f libntt.so
