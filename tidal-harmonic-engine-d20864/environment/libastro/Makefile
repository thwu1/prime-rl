CC = gcc
CFLAGS = -shared -fPIC -O2 -DNODE_RATE=0.05295377
TARGET = libastro.so

all: $(TARGET)

$(TARGET): astro.c
	$(CC) $(CFLAGS) -o $@ $< -lm

clean:
	rm -f $(TARGET)
