CC = gcc
CFLAGS = -O2 -Wall

all: libdual.a

libdual.a: dual.o
	ar rcs libdual.a dual.o

dual.o: dual.c dual.h
	$(CC) $(CFLAGS) -c dual.c -o dual.o

clean:
	rm -f *.o *.a
