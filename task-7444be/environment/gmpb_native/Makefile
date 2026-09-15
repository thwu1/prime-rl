CC = gcc
CFLAGS = -O2 -fPIC -Wall -std=c11
LDFLAGS = -shared

TARGET = libgmpb.so

all: $(TARGET)

$(TARGET): gmpb.c gmpb.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ gmpb.c

clean:
	rm -f $(TARGET)

.PHONY: all clean
