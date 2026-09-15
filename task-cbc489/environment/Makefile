CC = gcc
CFLAGS = -D_GNU_SOURCE -Wall -Wextra -std=gnu11 -O2 -pthread -Iinclude
LDFLAGS = -pthread

.PHONY: all clean

all: libbrc.a

libbrc.a: src/brc.o
	ar rcs $@ $^

src/brc.o: src/brc.c include/brc.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f src/brc.o libbrc.a
