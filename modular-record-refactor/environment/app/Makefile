CC = gcc
CFLAGS = -Wall -Wextra -O2
AR = ar
ARFLAGS = rcs

SRCS = record.c
OBJS = $(SRCS:.c=.o)
LIB = librecord.a

all: $(LIB) main

$(LIB): $(OBJS)
	$(AR) $(ARFLAGS) $@ $^

main: main.c $(LIB)
	$(CC) $(CFLAGS) -o $@ $< -L. -lrecord

%.o: %.c record.h
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f *.o $(LIB) main

.PHONY: all clean
