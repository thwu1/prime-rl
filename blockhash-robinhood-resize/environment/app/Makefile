CC      = gcc
CFLAGS  = -O2 -Wall -Wextra -fPIC -std=c11
LDFLAGS = -shared

.PHONY: all clean

all: libblockht.so

libblockht.so: hashtable.c hashtable.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ hashtable.c

clean:
	rm -f libblockht.so
