CC = gcc
CFLAGS = -shared -fPIC -O2 -Wall

all: libroofline.so

libroofline.so: roofline_core.c
	$(CC) $(CFLAGS) -o $@ $< -lm

clean:
	rm -f libroofline.so

.PHONY: all clean
