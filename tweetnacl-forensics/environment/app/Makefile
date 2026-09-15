CC = gcc
CFLAGS = -O2 -Wall -fPIC

all: libtweetnacl_reference.so libtweetnacl_suspect.so

libtweetnacl_reference.so: tweetnacl_reference.c randombytes.c tweetnacl.h
	$(CC) $(CFLAGS) -shared -o $@ tweetnacl_reference.c randombytes.c

libtweetnacl_suspect.so: tweetnacl_suspect.c randombytes.c tweetnacl.h
	$(CC) $(CFLAGS) -shared -o $@ tweetnacl_suspect.c randombytes.c

clean:
	rm -f *.so

.PHONY: clean all
