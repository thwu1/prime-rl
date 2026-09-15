CC = gcc
CFLAGS = -O2 -fPIC
LDFLAGS = -shared -lm

SRCS = src/sdf_prims.c
OBJS = $(SRCS:.c=.o)
TARGET = libsdf.so

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $^

src/%.o: src/%.c src/sdf.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f src/*.o $(TARGET)

.PHONY: all clean
