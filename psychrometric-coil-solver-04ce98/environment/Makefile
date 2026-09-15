CC = gcc
CFLAGS = -Wall -O2
LDFLAGS = -lm

psychro_calc: main.o psychro.o ahu.o
	$(CC) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

main.o: main.c psychro.h ahu.h
psychro.o: psychro.c psychro.h
ahu.o: ahu.c ahu.h psychro.h

clean:
	rm -f *.o psychro_calc

.PHONY: clean
