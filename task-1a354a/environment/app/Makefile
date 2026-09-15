CC      = gcc
CFLAGS  = -Wall -Wextra -O2 -Iinclude
LDFLAGS =

SRCS = src/main.c src/cache.c src/simulator.c src/protocol.c
OBJS = $(SRCS:.c=.o)
TARGET = mesi_sim

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $^

src/%.o: src/%.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
