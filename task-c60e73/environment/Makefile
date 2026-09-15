CC = gcc
CFLAGS = -O2 -Wall -Wextra -Wno-deprecated-declarations
LDFLAGS = -lssl -lcrypto

ed25519_tool: main.c ed25519.c ed25519.h
	$(CC) $(CFLAGS) -o $@ main.c ed25519.c $(LDFLAGS)

clean:
	rm -f ed25519_tool

.PHONY: clean
