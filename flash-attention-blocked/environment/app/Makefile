CC = gcc
CFLAGS = -O2 -Wall -fPIC

all: blocked_attention.so

blocked_attention.so: src/blocked_attention.c src/blocked_attention.h
	$(CC) $(CFLAGS) -shared -o $@ src/blocked_attention.c -lm

clean:
	rm -f blocked_attention.so libattention.so
