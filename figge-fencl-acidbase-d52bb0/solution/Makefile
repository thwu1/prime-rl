CC = gcc
CFLAGS = -shared -fPIC -O2
LDFLAGS = -lm
SRC = src/figge_core.c
TARGET = libfigge.so

.PHONY: build clean validate

build: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f $(TARGET)

validate: $(TARGET)
	python3 cli.py validate --data data/golden_data.csv
