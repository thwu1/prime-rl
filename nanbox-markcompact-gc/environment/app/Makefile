CC      = gcc
CFLAGS  = -Wall -Wextra -g -O0 -std=c11
TARGET  = vm_test

$(TARGET): main.c vm.c vm.h
	$(CC) $(CFLAGS) -o $(TARGET) main.c vm.c

clean:
	rm -f $(TARGET)

.PHONY: clean
