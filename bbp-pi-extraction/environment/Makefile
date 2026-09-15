CC = gcc
CFLAGS = -O2 -Wall
LDFLAGS = -lm
TARGET = pi_extract

all: $(TARGET)

$(TARGET): main.c pi_extract.c pi_extract.h
	$(CC) $(CFLAGS) -o $(TARGET) main.c pi_extract.c $(LDFLAGS)

clean:
	rm -f $(TARGET)

.PHONY: all clean
