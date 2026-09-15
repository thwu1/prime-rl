CC = gcc
CFLAGS = -Wall -O2
LEX = flex

minipratt: minipratt.c lex.yy.c tokens.h
	$(CC) $(CFLAGS) -o $@ minipratt.c lex.yy.c

lex.yy.c: lexer.l tokens.h
	$(LEX) lexer.l

clean:
	rm -f minipratt lex.yy.c

.PHONY: clean
