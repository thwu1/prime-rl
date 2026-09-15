CC = gcc
CFLAGS = -O2 -fPIC -Wall -std=c99
LDFLAGS = -shared -lm

libflip.so: flip_core.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

.PHONY: clean
clean:
	rm -f libflip.so
