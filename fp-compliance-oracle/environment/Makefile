CC = gcc
CFLAGS = -Wall -Wextra -std=c11 -frounding-math
LDFLAGS = -lm

TARGET = fp_oracle

all: $(TARGET)

$(TARGET): main.c fp_oracle.c fp_oracle.h
	$(CC) $(CFLAGS) -o $(TARGET) main.c fp_oracle.c $(LDFLAGS)

clean:
	rm -f $(TARGET)

.PHONY: all clean
