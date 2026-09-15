CC = gcc
CFLAGS = -Wall -Wextra -O2 -fPIC
LDFLAGS = -shared

TARGET = libbalance.so
SRCDIR = src
SRC = $(SRCDIR)/balance_core.c

all: $(TARGET)

$(TARGET): $(SRC) $(SRCDIR)/balance_core.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(SRC)

clean:
	rm -f $(TARGET)

.PHONY: all clean
