CC = gcc
CFLAGS = -O2 -Wall -Wextra -std=c11

all: vtterm libterminal.so

vtterm: main.c terminal.c terminal.h
	$(CC) $(CFLAGS) -o vtterm main.c terminal.c

libterminal.so: terminal.c terminal.h
	$(CC) $(CFLAGS) -fPIC -shared -o libterminal.so terminal.c

clean:
	rm -f vtterm libterminal.so

.PHONY: all clean
