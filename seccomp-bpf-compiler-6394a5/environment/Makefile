CC = gcc
CFLAGS = -Wall -Wextra -std=c11 -O2

bpf_compiler: bpf_compiler.c
	$(CC) $(CFLAGS) -o bpf_compiler bpf_compiler.c

filter.bpf: bpf_compiler policy.txt
	./bpf_compiler policy.txt filter.bpf

clean:
	rm -f bpf_compiler filter.bpf

.PHONY: clean
