CC = gcc
CFLAGS = -fopenmp -O2
LDFLAGS = -lm

SRCS = $(wildcard src/*.c)
NAMES = $(patsubst src/%.c,%,$(SRCS))

all: $(addprefix bin/,$(NAMES))

bin/%: src/%.c
	@mkdir -p bin
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -rf bin

.PHONY: all clean
