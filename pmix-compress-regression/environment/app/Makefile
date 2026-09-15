CC      = gcc
CFLAGS  = -Wall -Wextra -std=gnu11 -O2 -Iinclude
LDFLAGS = -lz -llz4

SRCDIR  = src
SRCS    = $(SRCDIR)/compress.c \
          $(SRCDIR)/compress_lz4.c \
          $(SRCDIR)/preg.c \
          $(SRCDIR)/preg_compress.c \
          $(SRCDIR)/preg_compress_v2.c \
          $(SRCDIR)/preg_raw.c \
          $(SRCDIR)/proc_map.c

OBJS    = $(SRCS:.c=.o)
TARGET  = test_ppn

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS) test_ppn.c
	$(CC) $(CFLAGS) -o $@ test_ppn.c $(OBJS) $(LDFLAGS)

$(SRCDIR)/%.o: $(SRCDIR)/%.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET)
