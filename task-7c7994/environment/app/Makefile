CC = gcc
CFLAGS = -Wall -Wextra -O2 -Iinclude
LDFLAGS =
BUILD = build
TARGET = $(BUILD)/secure_firmware

SRCS = src/secure_ops.c src/crypto_impl.c src/main.c
OBJS = $(patsubst src/%.c,$(BUILD)/%.o,$(SRCS))

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $^

$(BUILD)/%.o: src/%.c | $(BUILD)
	$(CC) $(CFLAGS) -c -o $@ $<

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)
