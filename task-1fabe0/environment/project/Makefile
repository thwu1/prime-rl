# Makefile for bare-metal Raspberry Pi 4 kernel + Device Tree overlay

CROSS   = aarch64-linux-gnu-
CC      = $(CROSS)gcc
LD      = $(CROSS)ld
OBJCOPY = $(CROSS)objcopy
DTC     = dtc

CFLAGS  = -Wall -O2 -ffreestanding -nostdlib -nostartfiles -mcpu=cortex-a72
LDFLAGS = -T link.ld

OBJS = start.o main.o uart.o

.PHONY: all clean

all: kernel8.img hat-overlay.dtbo

kernel8.elf: $(OBJS) link.ld
	$(LD) $(LDFLAGS) $(OBJS) -o $@

kernel8.img: kernel8.elf
	$(OBJCOPY) -O binary $< $@

hat-overlay.dtbo: hat-overlay.dts
	$(DTC) -@ -I dts -O dtb -o $@ $<

%.o: %.S
	$(CC) $(CFLAGS) -c $< -o $@

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f *.o kernel8.elf kernel8.img hat-overlay.dtbo
