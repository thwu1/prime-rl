CC = gcc
CFLAGS = -O2 -fPIC -Wall
TARGET = libso3.so

$(TARGET): so3_ops.c so3_ops.h
	$(CC) $(CFLAGS) -shared -o $@ $< -lm

clean:
	rm -f $(TARGET)

.PHONY: clean
