CC = gcc
CFLAGS = -shared -fPIC -O2
TARGET = libcpamm.so

all: $(TARGET)

$(TARGET): cpamm.c cpamm.h
	$(CC) $(CFLAGS) -o $@ cpamm.c -lm

clean:
	rm -f $(TARGET)

.PHONY: all clean
