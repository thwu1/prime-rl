CC = gcc
CFLAGS = -Wall -O2
TARGET = noc_sim

$(TARGET): noc_sim.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)

.PHONY: clean
