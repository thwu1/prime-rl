CC = gcc
CFLAGS = -O2 -Wall
TARGET = libcubic.so

all: $(TARGET)

$(TARGET): cubic_core.c
	$(CC) $(CFLAGS) -shared -o $@ $<

clean:
	rm -f $(TARGET)
