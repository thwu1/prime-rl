CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11 -I./include
LDFLAGS = -lm

.PHONY: all clean extract tools

all: extract tools

extract:
	@if [ ! -d cases ]; then tar xJf testdata.tar.xz; fi

tools: tools/mdl2json tools/nbt2json

tools/mdl2json: src/mdl2json.c include/nmms.h
	@mkdir -p tools
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

tools/nbt2json: src/nbt2json.c include/nmms.h
	@mkdir -p tools
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -rf tools/mdl2json tools/nbt2json cases
