
CC = gcc
CFLAGS = -Wall -Wextra -O2 -fPIC -Iinclude
LDFLAGS = -shared -lm

SRC = src/qmatmul.c src/reference.c
OBJ = $(SRC:.c=.o)
TARGET = libqmatmul.so

all: $(TARGET)

$(TARGET): $(OBJ)
	$(CC) $(LDFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f src/*.o $(TARGET)

debug: CFLAGS += -fsanitize=address -g -O0
debug: LDFLAGS += -fsanitize=address
debug: clean all

.PHONY: all clean debug
