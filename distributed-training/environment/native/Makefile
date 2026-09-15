CC = gcc
CFLAGS = -O2 -Wall -Wextra

all: cost_model_gen

cost_model_gen: cost_model_gen.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f cost_model_gen

.PHONY: all clean
