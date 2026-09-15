CC      = gcc
CFLAGS  = -O2 -Wall -Wextra -std=c11
LDFLAGS = -lm

TARGET = graph_analytics
SRCS   = main.c graph.c analytics.c
OBJS   = $(SRCS:.c=.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

main.o: main.c graph.h analytics.h
graph.o: graph.c graph.h
analytics.o: analytics.c analytics.h graph.h

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
