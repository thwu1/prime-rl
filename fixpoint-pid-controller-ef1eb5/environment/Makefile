CC = gcc
CFLAGS = -Wall -Wextra -O2 -std=c11

SIM = sim_harness

SRCS = sim_harness.c plant.c pid_controller.c
OBJS = $(SRCS:.c=.o)

all: $(SIM)

$(SIM): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(SIM)

run: $(SIM)
	./$(SIM)

.PHONY: all clean run
