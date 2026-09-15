CC = gcc
CFLAGS = -O2 -Wall -std=c99

poisson3d: poisson3d.c
	$(CC) $(CFLAGS) -o $@ $< -lm

clean:
	rm -f poisson3d

.PHONY: clean
