CC      = gcc
CFLAGS  = -Wall -Wextra -std=c11 -O2
LDFLAGS = -lm
TARGET  = compositor

SRCS = main.c scene_io.c compositor.c rasterizer.c
OBJS = $(SRCS:.c=.o)

$(TARGET): $(OBJS)
	$(CC) -o $@ $^ $(LDFLAGS)

%.o: %.c compositor.h scene_io.h rasterizer.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: clean
