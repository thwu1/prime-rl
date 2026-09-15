CC = gcc
CFLAGS = -O2 -fPIC -Wall
LDFLAGS = -shared -lm

all: libdopt.so

libdopt.so: dopt_kernel.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<

clean:
	rm -f libdopt.so

.PHONY: all clean
