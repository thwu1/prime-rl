CC = gcc
CFLAGS = -Wall -O2 -fPIC

all: lib/libsparse.so

lib/libsparse.so: src/sparse_ops.c src/sparse_ops.h
	@mkdir -p lib
	$(CC) $(CFLAGS) -shared -o $@ src/sparse_ops.c -lm

clean:
	rm -f lib/libsparse.so
