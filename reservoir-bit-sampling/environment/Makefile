CC = gcc
CFLAGS = -shared -fPIC -O2

all: libbitpool.so

libbitpool.so: bitpool.c bitpool.h
	$(CC) $(CFLAGS) -o $@ bitpool.c

clean:
	rm -f libbitpool.so
