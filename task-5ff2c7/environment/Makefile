CC = gcc
CFLAGS = -Wall -Wextra -O2 -fPIC

all: libkeccak.so

libkeccak.so: keccak.o
	$(CC) -shared -o $@ $<

keccak.o: keccak.c keccak.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f *.o libkeccak.so

.PHONY: all clean
