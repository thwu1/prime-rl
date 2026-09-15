CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11 -fPIC

all: libfastnum.so

libfastnum.so: fastnum.c fastnum.h
	$(CC) $(CFLAGS) -shared -o $@ fastnum.c

clean:
	rm -f libfastnum.so

.PHONY: all clean
