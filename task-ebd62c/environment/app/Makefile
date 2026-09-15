CC = gcc
CFLAGS = -fPIC -O2
LDFLAGS = -shared

all: libfem_core.so

libfem_core.so: src/elastic_core.c src/elastic_core.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ src/elastic_core.c

clean:
	rm -f libfem_core.so
