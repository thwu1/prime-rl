CC = gcc
CFLAGS = -Wall -Wextra -std=c11 -D_GNU_SOURCE -g -O2
LDFLAGS =

SRCS = main.c dispatch.c handlers.c types.c
OBJS = $(SRCS:.c=.o)
TARGET = cmdproc

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)

# Header dependencies
main.o: main.c dispatch.h handlers.h types.h
dispatch.o: dispatch.c dispatch.h handlers.h types.h
handlers.o: handlers.c handlers.h dispatch.h types.h
types.o: types.c types.h
