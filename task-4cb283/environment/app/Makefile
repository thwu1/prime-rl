CC = gcc
CFLAGS = -std=c11 -Wall -Wextra -pedantic -fPIC -g
CFGFLAGS = -DWITH_TABLE_CACHE
INCFLAGS = -Iinclude

SRCS = src/hamt.c src/cache.c src/murmur3.c src/uh.c
OBJS = $(SRCS:.c=.o)

LIB = libhamt.a

all: $(LIB)

$(LIB): $(OBJS)
	ar rcs $@ $^

%.o: %.c
	$(CC) -c $(CFLAGS) $(CFGFLAGS) $(INCFLAGS) -o $@ $<

clean:
	rm -f $(OBJS) $(LIB)

.PHONY: all clean
