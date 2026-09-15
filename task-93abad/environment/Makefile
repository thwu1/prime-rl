CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -fPIC

all: libexp2m1f.so

libexp2m1f.so: exp2m1f.c exp2m1f.h
	$(CC) $(CFLAGS) -shared -o $@ exp2m1f.c

clean:
	rm -f libexp2m1f.so

.PHONY: all clean
