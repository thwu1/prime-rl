CC = gcc
CFLAGS = -O2 -Wall -Wextra
LDFLAGS = -lm

TARGET = ctd_pipeline
SRCS = main.c gsw_pipeline.c
OBJS = $(SRCS:.c=.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

%.o: %.c gsw_pipeline.h gsw_check_data.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET) output.json

.PHONY: all clean
