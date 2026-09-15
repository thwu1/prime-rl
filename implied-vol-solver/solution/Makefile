CC = gcc
CFLAGS = -O2 -fPIC -Wall
LDFLAGS = -shared -lm

all: libivol.so

libivol.so: src/ivol.c src/ivol.h
	$(CC) $(CFLAGS) -o $@ src/ivol.c $(LDFLAGS)

clean:
	rm -f libivol.so

.PHONY: all clean
