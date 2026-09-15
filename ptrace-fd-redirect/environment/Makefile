CC = gcc
CFLAGS = -Wall -Wextra -g -O0

all: ptysession reporter

ptysession: ptysession.c
	$(CC) $(CFLAGS) -o $@ $<

reporter: reporter.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f ptysession reporter

.PHONY: all clean
