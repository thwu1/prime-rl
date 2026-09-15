CC = gcc
CFLAGS = -O2 -Wall -Wextra

.PHONY: all clean

all: emulator

emulator: emulator.c
	$(CC) $(CFLAGS) -o emulator emulator.c

clean:
	rm -f emulator
