CC = gcc
CFLAGS ?= -g -O0

all: test_driver

test_driver: buggy.c test_driver.c
	$(CC) $(CFLAGS) -o test_driver buggy.c test_driver.c

clean:
	rm -f test_driver *.gcno *.gcda *.gcov

.PHONY: all clean
