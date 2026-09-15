CC      = gcc
CFLAGS  = -Wall -Wextra -fPIC -O2
TARGET  = libdirichlet.so

all: $(TARGET)

$(TARGET): dirichlet.c dirichlet.h
	$(CC) $(CFLAGS) -shared -o $@ dirichlet.c -lm

clean:
	rm -f $(TARGET)

.PHONY: all clean
