CC = gcc
CFLAGS = -O2 -Wall

solver.so: solver.c
	$(CC) $(CFLAGS) -shared -o $@ $<

clean:
	rm -f solver.so
