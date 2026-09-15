CC = gcc
CFLAGS = -Wall -Wextra -O2
LDFLAGS = -lpthread

all: stress_test

stress_test: stress_test.c hashtable.c hashtable.h
	$(CC) $(CFLAGS) -o $@ stress_test.c hashtable.c $(LDFLAGS)

simulate: simulate.c
	$(CC) $(CFLAGS) -o $@ simulate.c

detect_cycle: detect_cycle.c
	$(CC) $(CFLAGS) -o $@ detect_cycle.c

clean:
	rm -f stress_test simulate detect_cycle

.PHONY: all clean
