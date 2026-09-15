
CC = gcc
CFLAGS = -O2 -fPIC -Wall
LDFLAGS = -shared -lm

TARGET = libscoring.so
SOURCES = scoring.c
HEADERS = scoring.h

all: $(TARGET)

$(TARGET): $(SOURCES) $(HEADERS)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(SOURCES)

clean:
	rm -f $(TARGET)

.PHONY: all clean
