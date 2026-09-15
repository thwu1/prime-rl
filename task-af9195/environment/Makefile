CC = gcc
CFLAGS = -O2 -fPIC -Wall
LDFLAGS = -shared

.PHONY: all clean

all: /app/libgmpb.so

/app/libgmpb.so: /app/src/gmpb.c /app/src/gmpb.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ /app/src/gmpb.c -lm

clean:
	rm -f /app/libgmpb.so
