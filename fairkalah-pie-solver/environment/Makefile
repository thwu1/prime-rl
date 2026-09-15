CC = gcc
CFLAGS = -O2 -fPIC -Wall -Wextra
TARGET = libkalah.so

all: $(TARGET)

$(TARGET): src/kalah_engine.c src/kalah_engine.h
	$(CC) $(CFLAGS) -shared -o $(TARGET) src/kalah_engine.c

clean:
	rm -f $(TARGET)

.PHONY: all clean
