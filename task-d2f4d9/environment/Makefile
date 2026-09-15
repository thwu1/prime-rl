CC = gcc
CFLAGS = -Wall

seccomp_loader: seccomp_loader.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f seccomp_loader

.PHONY: clean
