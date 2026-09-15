CC = gcc
CFLAGS = -Wall -O2

TARGET = libblockpool.a

all: $(TARGET)

$(TARGET): blockpool.c blockpool.h
	$(CC) $(CFLAGS) -c blockpool.c -o blockpool.o
	ar rcs $(TARGET) blockpool.o

clean:
	rm -f $(TARGET) blockpool.o
