CC = gcc
CFLAGS = -O2 -Wall

all: libdistances.so

distances.o: distances.c
	$(CC) $(CFLAGS) -c -o $@ $<

libdistances.so: distances.o
	ar rcs $@ $<

clean:
	rm -f *.o libdistances.so
