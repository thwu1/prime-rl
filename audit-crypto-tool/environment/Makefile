CC = gcc
CFLAGS = -Wall -Wextra -O2
LDFLAGS = -lsodium

cryptvault: cryptvault.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f cryptvault

.PHONY: clean
