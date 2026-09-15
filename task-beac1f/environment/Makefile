CC = gcc
CFLAGS = -Wall -Wextra -O2

all: test_harness

test_harness: test_harness.c pledge.c pledge.h
	$(CC) $(CFLAGS) -o test_harness test_harness.c pledge.c

clean:
	rm -f test_harness

.PHONY: all clean
