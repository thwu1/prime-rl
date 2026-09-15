CC = gcc
CFLAGS = -Wall -g

all: imgutil_driver

imgutil_driver: src/imgutil.c src/driver.c
	$(CC) $(CFLAGS) -o $@ $^

clean:
	rm -f imgutil_driver

.PHONY: all clean
