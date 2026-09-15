CC = gcc
CFLAGS = -O2 -Wall
LDFLAGS = -shared
TARGET = lib/flux_kernels.so

all: $(TARGET)

$(TARGET): src/flux_kernels.c src/flux_kernels.h
	mkdir -p lib
	$(CC) $(CFLAGS) $(LDFLAGS) -o $(TARGET) src/flux_kernels.c

clean:
	rm -f $(TARGET)

.PHONY: all clean
