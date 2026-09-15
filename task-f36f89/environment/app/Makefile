CROSS_COMPILE ?= arm-none-eabi-
CC := $(CROSS_COMPILE)gcc
OBJCOPY := $(CROSS_COMPILE)objcopy

CFLAGS = -fno-common -ffreestanding -O0 \
	 -gdwarf-2 -g3 -Wall -Werror \
	 -mcpu=cortex-m3 -mthumb \
	 -nostartfiles

# Source files — add your implementation files here
SRCS = startup.c os.c uart.c
LDSCRIPT = os.ld

TARGET = os.bin

all: $(TARGET)

os.elf: $(SRCS) $(LDSCRIPT)
	$(CC) $(CFLAGS) -T $(LDSCRIPT) $(SRCS) -o $@

$(TARGET): os.elf
	$(OBJCOPY) -O binary $< $@

qemu: $(TARGET)
	qemu-system-arm -M mps2-an385 -nographic -kernel $(TARGET)

clean:
	rm -f *.o *.elf *.bin *.list

.PHONY: all clean qemu
