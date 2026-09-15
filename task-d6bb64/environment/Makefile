CC = gcc
CFLAGS = -O2 -fPIC -Wall

all: libelliptic.a

libelliptic.a: libelliptic.o
	ar rcs $@ $^

libelliptic.o: libelliptic.c libelliptic.h
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f *.o *.a *.so
