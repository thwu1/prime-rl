CC = gcc
CFLAGS = -O2 -Wall -Wextra

all: kvstore

kvstore: src/main.c src/hashtable.c src/hashtable.h
	$(CC) $(CFLAGS) -o $@ src/main.c src/hashtable.c -Isrc

clean:
	rm -f kvstore

.PHONY: all clean
