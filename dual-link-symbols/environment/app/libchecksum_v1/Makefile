CC = gcc
CFLAGS = -Wall -O2

libchecksum.a: checksum.o
	ar rcs $@ $^

checksum.o: checksum.c checksum.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f *.o libchecksum.a

.PHONY: clean
