CC = gcc
CFLAGS = -Wall -Wextra -I/usr/local/include
LDFLAGS = -L/usr/local/lib -Wl,-rpath,/usr/local/lib -loqs

all: broken_kem hybrid_kem sig_matrix

broken_kem: broken_kem.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

hybrid_kem: hybrid_kem.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

sig_matrix: sig_matrix.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f broken_kem hybrid_kem sig_matrix

.PHONY: all clean
