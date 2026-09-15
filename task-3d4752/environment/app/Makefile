CC = gcc
CFLAGS = -Wall -Wextra -std=c11 -g
OBJS = main.o hsm.o test_sm.o

all: hsm_test

hsm_test: $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS)

%.o: %.c hsm.h test_sm.h
	$(CC) $(CFLAGS) -c $<

clean:
	rm -f *.o hsm_test

.PHONY: all clean
