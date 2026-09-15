CC = gcc
CFLAGS = -Wall -Wextra -std=c11 -O2
SRCS = main.c hsm.c qhsmtst.c trace.c
OBJS = $(SRCS:.c=.o)
TARGET = qhsmtst

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
