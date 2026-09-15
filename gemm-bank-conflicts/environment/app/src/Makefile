CC = gcc
CFLAGS = -shared -fPIC -O2

all: libbank.so

libbank.so: bank_model.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f libbank.so

.PHONY: all clean
