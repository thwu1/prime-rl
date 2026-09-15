CC      = arm-none-eabi-gcc
OBJDUMP = arm-none-eabi-objdump
SIZE    = arm-none-eabi-size

CFLAGS  = -mcpu=cortex-m4 -mthumb -mfloat-abi=soft \
          -O2 -Wall -Wextra -Wno-unused-parameter
LDFLAGS = -T linker.ld -nostartfiles --specs=nosys.specs \
          -Wl,-z,noexecstack

TARGET  = keyfob
SRCS    = startup.c crypto.c secure_keyfob.c
OBJS    = $(SRCS:.c=.o)

all: $(TARGET).elf

$(TARGET).elf: $(OBJS)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^
	$(SIZE) $@

%.o: %.c crypto.h
	$(CC) $(CFLAGS) -c -o $@ $<

disasm: $(TARGET).elf
	$(OBJDUMP) -d $< > $(TARGET).dis

clean:
	rm -f $(OBJS) $(TARGET).elf $(TARGET).dis $(TARGET).bin

.PHONY: all disasm clean
