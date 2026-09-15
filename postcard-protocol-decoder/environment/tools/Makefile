CC = gcc
CFLAGS = -Wall -Wextra -O2

all: frame_validator

frame_validator: frame_validator.c crc8.c crc8.h
	$(CC) $(CFLAGS) -o $@ frame_validator.c crc8.c

clean:
	rm -f frame_validator

.PHONY: all clean
