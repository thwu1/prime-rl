CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11

TARGET = libbf16.so

all: $(TARGET)

$(TARGET): bf16.c bf16.h
	$(CC) $(CFLAGS) -o $(TARGET) bf16.c

clean:
	rm -f $(TARGET)

.PHONY: all clean
