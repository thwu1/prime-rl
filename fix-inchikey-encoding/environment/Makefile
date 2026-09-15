
CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11
TARGET = inchikey_gen

SRCS = main.c inchikey.c sha256.c
OBJS = $(SRCS:.c=.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

main.o: main.c inchikey.h
inchikey.o: inchikey.c inchikey.h sha256.h
sha256.o: sha256.c sha256.h

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
