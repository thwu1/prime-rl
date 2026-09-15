CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c99
LDFLAGS =

all: lz4c

lz4c: main.c lz4_block.c lz4_block.h
	$(CC) $(CFLAGS) -o $@ main.c lz4_block.c $(LDFLAGS)

clean:
	rm -f lz4c

.PHONY: all clean
