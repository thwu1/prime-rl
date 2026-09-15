CC = gcc
CFLAGS = -O2 -Wall
TARGET = pipeline

all: $(TARGET)

$(TARGET): main.c pipeline.c pipeline.h
	$(CC) $(CFLAGS) -o $(TARGET) main.c pipeline.c -lm

clean:
	rm -f $(TARGET) output.txt
