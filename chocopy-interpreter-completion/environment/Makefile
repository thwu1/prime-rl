CC = gcc
CFLAGS = -std=c99 -Wall -g -I runtime

.PHONY: compile run clean

compile:
	@if [ -z "$(PROG)" ]; then echo "Usage: make compile PROG=programs/foo.py"; exit 1; fi
	@mkdir -p build
	python3 transpile.py $(PROG) build/output.c
	$(CC) $(CFLAGS) build/output.c runtime/runtime.c -o build/output

run: compile
	./build/output

clean:
	rm -rf build
