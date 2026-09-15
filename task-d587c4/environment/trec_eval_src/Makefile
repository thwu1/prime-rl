CC = gcc
CFLAGS = -O2 -Wall -std=c99

all: trec_eval

trec_eval: trec_eval.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f trec_eval

.PHONY: all clean
