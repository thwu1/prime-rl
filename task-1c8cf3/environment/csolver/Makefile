
CC = gcc
CFLAGS = -fPIC -O2 -Wall
LDFLAGS = -shared
LIBS = -llapack -lm

TARGET = libeigens.so

all: $(TARGET)

$(TARGET): eigensolve.c eigensolve.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ eigensolve.c $(LIBS)

clean:
	rm -f $(TARGET)

.PHONY: all clean
