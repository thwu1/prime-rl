CC = gcc
CFLAGS = -Wall -Wextra -O2
LDFLAGS_SESREC = -lutil

all: sesrec sesplay

sesrec: src/sesrec.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS_SESREC)

sesplay: src/sesplay.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f sesrec sesplay

.PHONY: all clean
