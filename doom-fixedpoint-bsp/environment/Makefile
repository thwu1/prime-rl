CC      = gcc
CFLAGS  = -Wall -O2
TARGET  = bsp_resolver

OBJS = main.o wad_reader.o fixed_math.o doom_math.o

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

main.o: main.c fixed_math.h wad_reader.h bsp.h
wad_reader.o: wad_reader.c wad_reader.h fixed_math.h
fixed_math.o: fixed_math.c fixed_math.h
doom_math.o: doom_math.c doom_math.h tantoangle_lut.h
bsp.o: bsp.c bsp.h fixed_math.h wad_reader.h tantoangle_lut.h

clean:
	rm -f *.o $(TARGET)

.PHONY: clean
