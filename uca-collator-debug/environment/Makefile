CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11
LDFLAGS =

SRC = src/implicit_weights.c
OBJ = $(SRC:.c=.o)
TARGET = lib/libimplicit.a

all: $(TARGET)

$(TARGET): $(OBJ)
	mkdir -p lib
	$(CC) $(LDFLAGS) -o $@ $^

src/%.o: src/%.c src/implicit_weights.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJ) $(TARGET)

.PHONY: all clean
