CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11 -D_DEFAULT_SOURCE -Wno-unused-parameter
LDFLAGS = -lm

SRCS = main.c value.c lisp.c
OBJS = $(SRCS:.c=.o)
TARGET = lisp

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

$(OBJS): value.h lisp.h

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
