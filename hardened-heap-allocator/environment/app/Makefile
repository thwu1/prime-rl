CC = gcc
CFLAGS = -O2 -Wall -Wextra -std=gnu11 -fPIC

all: allocator.o libhalloc.so

allocator.o: allocator.c allocator.h
	$(CC) $(CFLAGS) -c -o $@ allocator.c

libhalloc.so: allocator.c allocator.h
	$(CC) $(CFLAGS) -shared -o $@ allocator.c

clean:
	rm -f allocator.o libhalloc.so

.PHONY: all clean
