# Build libquad.so - C wrapper around GSL adaptive quadrature
CC = gcc
CFLAGS = -Wall -O2 -fPIC -I./src -I/usr/local/include/gsl
LDFLAGS = -lgsl -lm

all: libquad.so

libquad.so: src/quad_wrapper.c src/quad_wrapper.h
	$(CC) $(CFLAGS) -shared -o $@ src/quad_wrapper.c $(LDFLAGS)

clean:
	rm -f libquad.so

.PHONY: all clean
