CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11

all: verifier optimizer bcdump

verifier: verifier.c opcode_def.h
	$(CC) $(CFLAGS) -o verifier verifier.c

optimizer: optimizer.c opcode_def.h
	$(CC) $(CFLAGS) -o optimizer optimizer.c

bcdump: bcdump.c opcode_def.h
	$(CC) $(CFLAGS) -o bcdump bcdump.c

clean:
	rm -f verifier optimizer bcdump

.PHONY: all clean
