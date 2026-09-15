CC = gcc
CFLAGS = -O2 -fPIC -Wall -Wextra
TARGET = libquadrature.so

$(TARGET): quadrature.c quadrature.h
	$(CC) $(CFLAGS) -shared -o $(TARGET) quadrature.c -lm

clean:
	rm -f $(TARGET)

.PHONY: clean
