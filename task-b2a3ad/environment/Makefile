CC = gcc
CFLAGS = -O2 -Wall -Wextra -std=c99
TARGET = fdtd3d
SOURCES = main.c reference.c solver.c
OBJECTS = $(SOURCES:.c=.o)

$(TARGET): $(OBJECTS)
	$(CC) $(OBJECTS) -o $@

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJECTS) $(TARGET)

.PHONY: clean
