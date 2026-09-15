CC = gcc
CFLAGS = -shared -fPIC -O2

all: libaddrcalc.so

libaddrcalc.so: addr_calc.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f libaddrcalc.so

.PHONY: all clean
