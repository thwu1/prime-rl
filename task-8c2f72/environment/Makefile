CC      = gcc
MPICC   = mpicc
CFLAGS  = -O2 -Wall
LDFLAGS = -lm
MPIRUN  = mpirun --allow-run-as-root --oversubscribe --mca osc pt2pt

.PHONY: all run_parallel run_serial clean

all: solver_parallel solver_serial

solver_parallel: solver_parallel.c
	$(MPICC) $(CFLAGS) -o $@ $< $(LDFLAGS)

solver_serial: solver_serial.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

run_parallel: solver_parallel
	$(MPIRUN) -n 4 ./solver_parallel

run_serial: solver_serial
	./solver_serial

clean:
	rm -f solver_parallel solver_serial results.json serial_results.json
