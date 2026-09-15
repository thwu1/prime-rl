CC = gcc
CFLAGS = -fsanitize=address -fno-omit-frame-pointer -g -O1
LDFLAGS = -fsanitize=address -static-libasan

kvstore: src/kvstore.c
	$(CC) $(CFLAGS) -o kvstore src/kvstore.c $(LDFLAGS)

clean:
	rm -f kvstore

.PHONY: clean
