# Build the native discount factor shared library
CC = gcc
CFLAGS = -O2 -Wall

all: discount.dylib

discount.dylib: discount.c
	$(CC) $(CFLAGS) -shared -o $@ $<

clean:
	rm -f discount.dylib
