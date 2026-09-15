CC      = mpicc
CFLAGS  = -O2 -std=c99 -Wall
LDFLAGS = -lm

all: laplace_solver

laplace_solver: main.o pgas_array.o
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

main.o: main.c pgas_array.h
	$(CC) $(CFLAGS) -c -o $@ $<

pgas_array.o: pgas_array.c pgas_array.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f *.o laplace_solver /app/output.txt

.PHONY: all clean
