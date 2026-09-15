CC = gcc
CFLAGS = -Wall -Wextra -O2 -fPIC
TARGET = libfp8.so

all: $(TARGET)

# TODO: Add build rule to compile fp8.c into a shared library.
# The library must be position-independent (-fPIC, -shared) and link -lm.

clean:
	rm -f $(TARGET) *.o

.PHONY: all clean
