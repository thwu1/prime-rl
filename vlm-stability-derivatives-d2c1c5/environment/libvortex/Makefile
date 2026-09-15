CC      = gcc
CFLAGS  = -O2 -fPIC -Wall
TARGET  = libvortex.so

all: $(TARGET)

$(TARGET): biot_savart.o
	$(CC) -shared -o $@ $^ -lm

biot_savart.o: biot_savart.c vortex.h
	$(CC) $(CFLAGS) -c biot_savart.c -o $@

clean:
	rm -f *.o $(TARGET)

.PHONY: all clean
