CC      = gcc
CFLAGS  = -w -std=c11 -g -O2
LDFLAGS =

all: test_shaper

shaper.o: shaper.c shaper.h
	$(CC) $(CFLAGS) -c -o $@ $<

test_shaper.o: test_shaper.c shaper.h
	$(CC) $(CFLAGS) -c -o $@ $<

test_shaper: test_shaper.o shaper.o
	$(CC) -o $@ $^ $(LDFLAGS)

sanitize: CFLAGS = -Wall -Wextra -std=c11 -g -O0 -fsanitize=addresses -fno-omit-frame-pointer
sanitize: LDFLAGS = -fsanitize=addresses -static-libasan
sanitize: clean all

clean:
	rm -f *.o test_shaper

.PHONY: all clean sanitize
