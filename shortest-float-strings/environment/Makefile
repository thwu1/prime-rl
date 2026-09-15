CC = gcc
CFLAGS = -O2 -Wall -std=c11
LDFLAGS = -lm

SRC_DIR = src
BUILD_DIR = build

.PHONY: all clean

all: $(BUILD_DIR)/naive_convert $(BUILD_DIR)/fast_convert

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/naive_convert: $(SRC_DIR)/naive_convert.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

$(BUILD_DIR)/fast_convert: $(SRC_DIR)/fast_convert.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -rf $(BUILD_DIR)
