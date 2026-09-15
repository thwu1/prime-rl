CC = gcc
CFLAGS = -Wall -Wextra -O2
TARGET = pkt_engine

all: $(TARGET)

$(TARGET): pkt_engine.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)

.PHONY: all clean
