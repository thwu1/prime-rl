CC = gcc
CFLAGS = -O2 -Wall -Wextra -fPIC

libregion.so: region.c
	$(CC) $(CFLAGS) -shared -o $@ region.c

clean:
	rm -f libregion.so

.PHONY: clean
