CC = gcc
CFLAGS = -O2 -Wall

all: tokenizer

tokenizer: lex.yy.c
	$(CC) $(CFLAGS) -o $@ $<

lex.yy.c: cool.l
	flex $<

clean:
	rm -f tokenizer lex.yy.c

.PHONY: all clean
