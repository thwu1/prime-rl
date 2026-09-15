CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11
OBJS = main.o parser.o layout.o output.o
TARGET = assembler

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^

%.o: %.c assembler.h
	$(CC) $(CFLAGS) -c $<

debug:
	$(MAKE) clean
	$(MAKE) all CFLAGS="-Wall -Wextra -std=c11 -g -O0"

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean debug
