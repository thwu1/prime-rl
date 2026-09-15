CC = gcc
CFLAGS = -O2 -Wall
LDFLAGS = -lm
TARGET = libbrdf.a

all: $(TARGET)

$(TARGET): brdf_kernel.o
	ar rcs $@ $<

brdf_kernel.o: brdf_kernel.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f *.o $(TARGET)
