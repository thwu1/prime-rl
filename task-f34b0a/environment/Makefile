CC = gcc
CFLAGS = -O2 -Wall -Wextra -std=c99
LDFLAGS = -lm

all: test_driver

test_driver: test_driver.c posit16.c posit16.h
	$(CC) $(CFLAGS) -o $@ test_driver.c posit16.c $(LDFLAGS)

clean:
	rm -f test_driver

.PHONY: all clean
