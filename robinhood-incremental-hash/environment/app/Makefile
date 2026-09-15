CC      = gcc
CFLAGS  = -O2 -Wall -Wextra -std=c11

all: hashmap_test libhashmap.so

hashmap_test: main.c hashmap.c hashmap.h
	$(CC) $(CFLAGS) -o $@ main.c hashmap.c

libhashmap.so: hashmap.c hashmap.h
	$(CC) $(CFLAGS) -shared -fPIC -o $@ hashmap.c

clean:
	rm -f hashmap_test libhashmap.so

.PHONY: all clean
