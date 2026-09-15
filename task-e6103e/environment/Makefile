CC = gcc
CFLAGS = -shared -fPIC -O2 -Wall

libnode_ops.so: node_ops.c node_ops.h
	$(CC) $(CFLAGS) -o $@ node_ops.c

clean:
	rm -f libnode_ops.so

.PHONY: clean
