CC      = gcc
CFLAGS  = -Wall -Wextra -O2 -DOPENSSL_SUPPRESS_DEPRECATED
LDFLAGS = -lcrypto

all: secure_kem test_roundtrip

secure_kem: rsa_kem.o util.o main.o
	$(CC) -o $@ $^ $(LDFLAGS)

test_roundtrip: rsa_kem.o util.o test_roundtrip.o
	$(CC) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

rsa_kem.o: rsa_kem.c rsa_kem.h
main.o: main.c rsa_kem.h util.h
util.o: util.c util.h
test_roundtrip.o: test_roundtrip.c rsa_kem.h util.h

clean:
	rm -f *.o secure_kem test_roundtrip

.PHONY: all clean
