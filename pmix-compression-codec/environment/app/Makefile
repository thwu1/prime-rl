CC      = gcc
CFLAGS  = -Wall -Wextra -O2 -std=gnu11
LDLIBS  = -lz

SRCS    = ppn_codec.c main.c
OBJS    = $(SRCS:.c=.o)
TARGET  = ppn_test

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDLIBS)

%.o: %.c ppn_codec.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)
