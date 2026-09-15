CC      = gcc
CFLAGS  = -std=gnu11 -O2 -Wall -Wextra -pthread
TARGET  = test_runner

all: $(TARGET)

$(TARGET): test_runner.c signal_tree.c signal_tree.h
	$(CC) $(CFLAGS) -o $@ test_runner.c signal_tree.c

clean:
	rm -f $(TARGET)

.PHONY: all clean
