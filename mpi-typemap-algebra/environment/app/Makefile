CC = gcc
CFLAGS = -Wall -Wextra -O2
LDFLAGS = -lmpi

mpi_validate: mpi_validate.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

.PHONY: clean
clean:
	rm -f mpi_validate
