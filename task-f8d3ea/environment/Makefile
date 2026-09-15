CC = gcc
CFLAGS = -O2 -Wall

mseed3pack: mseed3pack.c sinedata.h mseedformat.h
	$(CC) $(CFLAGS) -o mseed3pack mseed3pack.c

clean:
	rm -f mseed3pack output.mseed3

.PHONY: clean
