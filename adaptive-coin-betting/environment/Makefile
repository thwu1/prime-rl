CC = gcc
CFLAGS = -shared -fPIC -O2
LDFLAGS = -lm

all: lib/libadversary.so

lib/libadversary.so: lib/adversary.c lib/adversary.h
	$(CC) $(CFLAGS) -o $@ lib/adversary.c $(LDFLAGS)

clean:
	rm -f lib/libadversary.so

.PHONY: all clean
