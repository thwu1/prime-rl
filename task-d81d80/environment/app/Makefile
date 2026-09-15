CC = gcc
CFLAGS = -shared -fPIC -O2

all: libmotion.so

libmotion.so: motion_model.c
	$(CC) $(CFLAGS) -o $@ $< -lm

clean:
	rm -f libmotion.so

.PHONY: all clean
