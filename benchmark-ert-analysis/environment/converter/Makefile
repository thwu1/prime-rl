CC = gcc
CFLAGS = -Wall -O2
LDLIBS = -lm

converter: converter.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f converter

.PHONY: clean
