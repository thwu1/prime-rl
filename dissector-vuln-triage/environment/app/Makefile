CC = gcc
CFLAGS = -Wall -O2
ASAN_FLAGS = -fsanitize=address -fno-omit-frame-pointer -g -O1

SRCS = src/main.c src/probe.c src/ident.c src/auth.c src/bulk.c src/diag.c src/util.c

all: ndp

ndp: $(SRCS) src/ndp.h
	$(CC) $(CFLAGS) -o $@ $(SRCS)

asan: $(SRCS) src/ndp.h
	$(CC) $(CFLAGS) $(ASAN_FLAGS) -o ndp_asan $(SRCS)

clean:
	rm -f ndp ndp_asan

.PHONY: all asan clean
