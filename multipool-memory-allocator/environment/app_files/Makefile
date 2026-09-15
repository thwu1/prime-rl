CC      = gcc
CFLAGS  = -Wall -Wextra -fPIC -Iinclude -std=gnu11 -O2 -g -pthread
LDFLAGS = -shared -pthread

all: liballocator.so

liballocator.so: src/allocator.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<

clean:
	rm -f liballocator.so

.PHONY: all clean
