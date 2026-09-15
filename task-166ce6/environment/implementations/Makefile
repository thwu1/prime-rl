CC = gcc
CFLAGS = -O2 -Wall -Wextra
LDFLAGS = -lgmp

all: alpha beta gamma

alpha: main.c impl_alpha.c
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

beta: main.c impl_beta.c
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

gamma: main.c impl_gamma.c
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

clean:
	rm -f alpha beta gamma

.PHONY: all clean
