CC = gcc
CFLAGS = -Wall -O2 -fPIC

TARGET = libsgwt.so

all: $(TARGET)

$(TARGET): sgwt_native/cheby.c
	$(CC) $(CFLAGS) -shared -o $@ $<

clean:
	rm -f $(TARGET)
