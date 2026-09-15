CC = gcc
CFLAGS = -shared -fPIC -O2 -Wall

.PHONY: all clean

all: viterbi.so

viterbi.so: viterbi.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f viterbi.so
