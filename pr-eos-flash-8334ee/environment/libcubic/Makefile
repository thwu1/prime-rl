CC = gcc
CFLAGS = -O2

all: libcubic.so

libcubic.so: cubic_solver.c
	$(CC) $(CFLAGS) -c -o $@ $< -lm

clean:
	rm -f *.o *.so
