CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c99
TARGET = decode_png

all: $(TARGET) libdecode_png.so

$(TARGET): decode_png.c
	$(CC) $(CFLAGS) -o $@ $<

libdecode_png.so: decode_png.c decode_png.h
	$(CC) $(CFLAGS) -shared -fPIC -DBUILD_SHARED -o $@ $<

clean:
	rm -f $(TARGET) libdecode_png.so

.PHONY: all clean
