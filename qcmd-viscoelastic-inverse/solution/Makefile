CC = gcc
CFLAGS = -fPIC -O2 -std=c99 -Wall
LDFLAGS = -shared -lm

all: libqcm_transfer.so

libqcm_transfer.so: qcm_transfer.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<

clean:
	rm -f libqcm_transfer.so

.PHONY: all clean
