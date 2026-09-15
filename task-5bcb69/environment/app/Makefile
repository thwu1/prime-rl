CC = gcc
CFLAGS = -O2 -g -Wall -Wextra -std=c11
LDFLAGS = -lmpfr -lgmp -lm

.PHONY: all clean

all: spot_check

spot_check: spot_check.c cbrtf.c cbrtf.h
	$(CC) $(CFLAGS) -o $@ spot_check.c cbrtf.c $(LDFLAGS)

clean:
	rm -f spot_check
