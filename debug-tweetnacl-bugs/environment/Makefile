CC = gcc
CFLAGS = -O2 -Wall -Wextra
LDFLAGS =

all: nacl_vault

nacl_vault: nacl_vault.c tweetnacl.c randombytes.c tweetnacl.h
	$(CC) $(CFLAGS) -o nacl_vault nacl_vault.c tweetnacl.c randombytes.c $(LDFLAGS)

clean:
	rm -f nacl_vault

.PHONY: all clean
