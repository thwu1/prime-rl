CC      = gcc
CFLAGS  = -shared -fPIC -O2 -Wall
TARGET  = libintegrators.so

all: $(TARGET)

$(TARGET): integrators.c integrators.h
	$(CC) $(CFLAGS) -o $(TARGET) integrators.c

clean:
	rm -f $(TARGET)

.PHONY: all clean
