CC = gcc
CFLAGS = -std=c11 -Wall -Wextra -Wpedantic -g -O0
SRCS = main.c hsm.c test_sm.c
TARGET = hsm_test

all: $(TARGET)

$(TARGET): $(SRCS) hsm.h test_sm.h
	$(CC) $(CFLAGS) -o $@ $(SRCS)

clean:
	rm -f $(TARGET)

.PHONY: all clean
