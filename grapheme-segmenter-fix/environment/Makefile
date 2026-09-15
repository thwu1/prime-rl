CC = gcc
CFLAGS = -O2 -shared -fPIC
PYTHON = python3

.PHONY: all clean

all: libwordbreak.so libsentbreak.so

word_tables.c: gen_word_tables.py data/WordBreakProperty.txt data/emoji-data.txt
	$(PYTHON) gen_word_tables.py

libwordbreak.so: word_tables.c
	$(CC) $(CFLAGS) -o $@ $<

sentence_tables.c: gen_sentence_tables.py data/SentenceBreakProperty.txt
	$(PYTHON) gen_sentence_tables.py

libsentbreak.so: sentence_tables.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f word_tables.c sentence_tables.c libwordbreak.so libsentbreak.so
