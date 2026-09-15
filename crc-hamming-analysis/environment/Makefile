CC = gcc
CFLAGS = -O2 -Wall -Wextra -std=c11

crc_engine: crc_engine.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f crc_engine

.PHONY: clean
