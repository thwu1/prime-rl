CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11 -Wno-format-truncation
LDFLAGS =

all: test_driver

test_driver: test_driver.o regex_engine.o
	$(CC) $(LDFLAGS) -o $@ $^

test_driver.o: test_driver.c regex_engine.h
	$(CC) $(CFLAGS) -c -o $@ $<

regex_engine.o: regex_engine.c regex_engine.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f *.o test_driver

.PHONY: all clean
