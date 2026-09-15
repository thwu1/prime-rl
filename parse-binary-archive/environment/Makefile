CC = gcc
CFLAGS = -O2 -fPIC -Wall

.PHONY: all clean

all: parsers/libparser_alpha.so parsers/libparser_beta.so parsers/libparser_gamma.so

parsers/libparser_alpha.so: parsers/parser_alpha.c
	$(CC) -shared $(CFLAGS) -o $@ $< -lm

parsers/libparser_beta.so: parsers/parser_beta.c
	$(CC) -shared $(CFLAGS) -o $@ $< -lm

parsers/libparser_gamma.so: parsers/parser_gamma.c
	$(CC) -shared $(CFLAGS) -o $@ $< -lm

libconformant.so: src/conformant.c
	$(CC) -shared $(CFLAGS) -o $@ $< -lm

clean:
	rm -f parsers/*.so libconformant.so
