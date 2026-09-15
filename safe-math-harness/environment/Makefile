CC = gcc
CFLAGS = -Wall -Wextra -std=c11 -O2
CFLAGS_SAN = -fsanitize=undefined -fno-sanitize-recover=all -std=c11 -O0
CFLAGS_COV = -std=c11 -O0

expr_gen: expr_gen.c
	$(CC) $(CFLAGS) -o expr_gen expr_gen.c

expr_gen-san: expr_gen.c
	$(CC) $(CFLAGS_SAN) -o expr_gen expr_gen.c

coverage: expr_gen.c
	$(CC) $(CFLAGS_COV) -o expr_gen_cov expr_gen.c
	@echo "Coverage build complete. Run tests and gcov for results."

clean:
	rm -f expr_gen expr_gen_cov

.PHONY: clean coverage
