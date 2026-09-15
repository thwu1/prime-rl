CC = gcc
TSAN_CC = clang
CFLAGS = -O2 -fopenmp
TSAN_CFLAGS = -O1 -g -fsanitize=thread -fopenmp

SOURCES = $(wildcard src/*.c)
TARGETS = $(patsubst src/%.c,build/%,$(SOURCES))
TSAN_TARGETS = $(patsubst src/%.c,build/%_tsan,$(SOURCES))

all: $(TARGETS)

tsan: $(TSAN_TARGETS)

build:
	mkdir -p build

build/%: src/%.c | build
	$(CC) $(CFLAGS) $< -o $@ -lm

build/%_tsan: src/%.c | build
	$(TSAN_CC) $(TSAN_CFLAGS) $< -o $@ -lm

clean:
	rm -rf build

.PHONY: all tsan clean
