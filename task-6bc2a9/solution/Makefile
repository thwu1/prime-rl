CC = gcc
CFLAGS = -O2 -fPIC -Wall
TARGET = libpeaks.so

all: $(TARGET)

$(TARGET): peaks.c
	$(CC) $(CFLAGS) -shared -o $@ $< -lm

clean:
	rm -f $(TARGET)

.PHONY: all clean
