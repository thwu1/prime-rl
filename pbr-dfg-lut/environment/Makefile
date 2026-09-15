CC = gcc
CFLAGS = -O2 -Wall

all: dfg_reference lut_compare

dfg_reference: src/dfg_reference.c
	$(CC) $(CFLAGS) -o $@ $< -lm

lut_compare: src/lut_compare.c
	$(CC) $(CFLAGS) -o $@ $< -lm

clean:
	rm -f dfg_reference lut_compare

.PHONY: all clean
