# Build the micro-Decaf to TAC parser
CC = gcc

all: decaf2tac

parser.tab.c parser.tab.h: parser.y
	bison -d parser.y

lex.yy.c: scanner.l parser.tab.h
	flex scanner.l

lex.yy.o: lex.yy.c parser.tab.h
	$(CC) -c lex.yy.c

parser.tab.o: parser.tab.c
	$(CC) -c parser.tab.c

decaf2tac: lex.yy.o parser.tab.o
	$(CC) -o $@ $^

clean:
	rm -f decaf2tac lex.yy.c lex.yy.o parser.tab.c parser.tab.h parser.tab.o

.PHONY: all clean
