CC = gcc
CFLAGS = -shared -fPIC

.PHONY: all run clean

all: libcorr.so run

libcorr.so: correlations/native_impl.c
	$(CC) $(CFLAGS) -o libcorr.so correlations/native_impl.c -lm

run: libcorr.so
	python3 pipeline.py

clean:
	rm -f libcorr.so results.db
