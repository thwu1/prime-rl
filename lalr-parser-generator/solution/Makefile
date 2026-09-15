CC = gcc
CFLAGS = -std=c99 -O2 -Wall -Werror -pedantic
LALR_GEN = ./lalr_gen
GRAMMAR_DIR = grammars
BUILD_DIR = build

GRAMMARS = $(wildcard $(GRAMMAR_DIR)/*.cfg)
PARSERS = $(patsubst $(GRAMMAR_DIR)/%.cfg,$(BUILD_DIR)/parser-%,$(GRAMMARS))

.PHONY: all clean

all: $(PARSERS)

$(BUILD_DIR)/parser-%: $(GRAMMAR_DIR)/%.cfg $(LALR_GEN) | $(BUILD_DIR)
	$(LALR_GEN) $< > $(BUILD_DIR)/$*.c
	$(CC) $(CFLAGS) -o $@ $(BUILD_DIR)/$*.c

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

clean:
	rm -rf $(BUILD_DIR)
