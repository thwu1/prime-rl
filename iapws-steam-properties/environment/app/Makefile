CC = gcc
CFLAGS = -O2 -fPIC -Wall
LDFLAGS = -shared -lm

all: libif97.so

libif97.so: src/if97_core.c src/if97_core.h
	$(CC) $(CFLAGS) -o $@ src/if97_core.c $(LDFLAGS)

clean:
	rm -f libif97.so

.PHONY: all clean
