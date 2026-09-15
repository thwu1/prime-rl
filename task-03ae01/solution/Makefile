CC = gcc
CFLAGS = -O2
LEX = flex

all: cool_lexer

cool_lexer: lex.yy.c lex_main.c json_escape.h
	$(CC) $(CFLAGS) -o cool_lexer lex.yy.c lex_main.c

lex.yy.c: cool.l json_escape.h
	$(LEX) -o lex.yy.c cool.l

clean:
	rm -f cool_lexer lex.yy.c

.PHONY: all clean
