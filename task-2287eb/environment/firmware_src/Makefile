CC = arm-none-eabi-gcc
STRIP = arm-none-eabi-strip

CFLAGS = -mcpu=cortex-m4 -mthumb -O1 -ffreestanding -nostdlib
CFLAGS += -ffunction-sections -fdata-sections -Wall

LDFLAGS = -T linker.ld -nostdlib -nostartfiles
LDFLAGS += -Wl,--gc-sections

all: firmware.elf

firmware.elf: startup.o main.o
	$(CC) $(CFLAGS) $(LDFLAGS) -o firmware_full.elf startup.o main.o
	$(STRIP) --strip-all firmware_full.elf -o firmware.elf

startup.o: startup.s
	$(CC) $(CFLAGS) -c -o $@ $<

main.o: main.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f *.o *.elf

.PHONY: all clean
