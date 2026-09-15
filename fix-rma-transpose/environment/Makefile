CC = mpicc
CFLAGS = -Wall -O2

jacobi_seq: jacobi_seq.c
	gcc $(CFLAGS) -o $@ $<

jacobi_rma: jacobi_rma.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f jacobi_seq jacobi_rma

.PHONY: clean
