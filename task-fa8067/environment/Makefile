CC      = gcc
CFLAGS  = -O2 -Wall -Wextra -fPIC -std=c11
LDFLAGS = -shared

all: libblockht.so

libblockht.so: blockht.c blockht.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ blockht.c

clean:
	rm -f libblockht.so

.PHONY: all clean
