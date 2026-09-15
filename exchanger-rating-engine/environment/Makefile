CC = gcc
CFLAGS = -shared -fPIC -O2

libcorr.so: libcorr.c
	$(CC) $(CFLAGS) -o $@ $< -lm

clean:
	rm -f libcorr.so

.PHONY: clean
