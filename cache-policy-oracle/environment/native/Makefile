CC = gcc
CFLAGS = -Wall -O2

all: cachesim.a

cachesim.a: cachesim.c cachesim.h
	$(CC) $(CFLAGS) -c cachesim.c -o cachesim.a

clean:
	rm -f cachesim.a *.o
