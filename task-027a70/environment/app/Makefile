CC = gcc
CFLAGS = -O2 -Wall
LDFLAGS =

all: freqresp

freqresp: freqresp.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

validate: freqresp
	python3 /app/gen_zpk.py
	@echo "ZPK files generated. Run ./freqresp <zpk_file> to analyze."

clean:
	rm -f freqresp /app/zpk_*.txt

.PHONY: clean validate all
