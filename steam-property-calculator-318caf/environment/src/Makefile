CC = gcc
CFLAGS = -O2 -Wall

all: libif97.a

if97_core.o: if97_core.c if97_core.h
	$(CC) $(CFLAGS) -c if97_core.c -o if97_core.o

libif97.a: if97_core.o
	ar rcs libif97.a if97_core.o

clean:
	rm -f *.o *.a
