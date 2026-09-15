CC = gcc
CFLAGS = -O2 -Wall -Wextra -std=c11
TARGET = emu6502

all: $(TARGET)

$(TARGET): main.c cpu6502.c cpu6502.h
	$(CC) $(CFLAGS) -o $(TARGET) main.c cpu6502.c

clean:
	rm -f $(TARGET)

.PHONY: all clean
