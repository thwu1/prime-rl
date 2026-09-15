CC = gcc
CFLAGS = -Wall -std=c11 -O1 -g -I.
AR = ar

.PHONY: all clean asan valgrind

all: libgc.a

libgc.a: gc.o
	$(AR) rcs $@ $<

gc.o: gc.c gc.h
	$(CC) $(CFLAGS) -c -o $@ gc.c

asan:
	$(CC) -Wall -std=c11 -O1 -g -I. -fsanitize=address -static-libasan -o /tmp/test_basic_asan /tests/test_basic.c gc.c
	ASAN_OPTIONS=detect_leaks=0 /tmp/test_basic_asan

valgrind:
	$(CC) $(CFLAGS) -o /tmp/test_basic_vg /tests/test_basic.c gc.c
	valgrind --leak-check=full --error-exitcode=1 --xml=yes --xml-file=valgrind-report.xml /tmp/test_basic_vg

clean:
	rm -f gc.o libgc.a valgrind-report.xml /tmp/test_basic_asan /tmp/test_basic_vg
