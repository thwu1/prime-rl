CC = gcc
CFLAGS = -Wall -Wextra -O2

all: recorder replayer

recorder: recorder.c
	$(CC) $(CFLAGS) -o $@ $<

replayer: replayer.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f recorder replayer *.dat *.tim

.PHONY: all clean
