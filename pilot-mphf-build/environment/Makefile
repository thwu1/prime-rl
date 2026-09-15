CC      = gcc
CFLAGS  = -O2 -Wall -Wextra -fPIC

all: libmphf.so

libmphf.so: mphf.c mphf.h
	$(CC) $(CFLAGS) -shared -o $@ mphf.c -lm

clean:
	rm -f libmphf.so

.PHONY: all clean
