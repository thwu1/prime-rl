CC = gcc
CFLAGS = -Wall -Wno-unused-result -I./magma -I./src

ifeq ($(CANARIES),1)
CFLAGS += -DMAGMA_ENABLE_CANARIES
endif

ifeq ($(FIXES),1)
CFLAGS += -DMAGMA_ENABLE_FIXES
endif

all: imgparse monitor

imgparse: src/parser.c src/main.c magma/runtime.c
	$(CC) $(CFLAGS) -o $@ $^

monitor: magma/monitor.c
	$(CC) -Wall -I./magma -o $@ $<

clean:
	rm -f imgparse monitor

.PHONY: all clean
