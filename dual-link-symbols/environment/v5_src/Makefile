CC = gcc
CFLAGS = -fPIC -Wall -O2

all: libprocessor.so.5

libprocessor.so.5: processor.o
	$(CC) -shared -Wl,-soname,$@ -o $@ $^ -lm

processor.o: processor.c processor.h
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f *.o *.so*
