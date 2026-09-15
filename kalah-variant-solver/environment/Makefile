CC = gcc
CFLAGS = -O2 -Wall -Wextra

all: kalah-engine

kalah-engine: kalah_engine.c
	$(CC) $(CFLAGS) -o kalah-engine kalah_engine.c

clean:
	rm -f kalah-engine

.PHONY: all clean
