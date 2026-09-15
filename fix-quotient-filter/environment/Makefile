CC      = gcc
CFLAGS  = -Wall -Wextra -O2 -fPIC -std=c11
LDFLAGS = -shared -lm

TARGET  = libcqf.so
SRCS    = cqf.c cqf_hash.c
OBJS    = $(SRCS:.c=.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

cqf.o: cqf.c cqf.h cqf_hash.h
cqf_hash.o: cqf_hash.c cqf_hash.h

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
