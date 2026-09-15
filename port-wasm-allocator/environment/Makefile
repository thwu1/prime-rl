CC ?= gcc
CFLAGS = -Wall -Wextra -O2 -fPIC -DNDEBUG
LDFLAGS = -shared

.PHONY: all clean

all: libwalloc.so

libwalloc.so: walloc_native.c walloc.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ walloc_native.c

clean:
	rm -f libwalloc.so
