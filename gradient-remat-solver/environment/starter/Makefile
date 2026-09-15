CC = gcc
CFLAGS = -O2 -fPIC -Wall

dp_core.so: dp_core.c
	$(CC) $(CFLAGS) -shared -o $@ $< -lm

clean:
	rm -f dp_core.so

.PHONY: clean
