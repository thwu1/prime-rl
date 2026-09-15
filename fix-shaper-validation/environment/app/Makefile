CC      = gcc
CFLAGS  = -Wall -Wextra -std=c11 -fPIC -O2
TARGET  = libshaper.so

all: $(TARGET)

$(TARGET): shaper.c shaper.h
	$(CC) $(CFLAGS) -shared -o $@ shaper.c

clean:
	rm -f $(TARGET)

.PHONY: all clean
