CC = gcc
CFLAGS = -O2 -Wall -Wextra -std=c11 -Iinclude
LDFLAGS = -lm
SRCS = $(wildcard *.c)
OBJS = $(SRCS:.c=.o)

engine: $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f engine libengine.so *.o

.PHONY: clean
