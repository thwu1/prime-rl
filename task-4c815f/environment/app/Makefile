CC = gcc
CFLAGS = -Wall -Wextra -g -O0 -Isrc
ASAN_FLAGS = -fsanitize=address -fno-omit-frame-pointer -static-libasan
SRC = src/vdriver.c src/handlers.c src/pool.c
TARGET = vdriver
TARGET_ASAN = vdriver_asan

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $^

asan: $(SRC)
	$(CC) $(CFLAGS) $(ASAN_FLAGS) -o $(TARGET_ASAN) $^

clean:
	rm -f $(TARGET) $(TARGET_ASAN)

.PHONY: all asan clean
