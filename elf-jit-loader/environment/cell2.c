extern int add(int, int);
extern int multiply(int, int);
extern int get_shared(void);

int compute_sum(void) { return add(get_shared(), 8); }
int compute_product(void) { return multiply(get_shared(), 3); }
int quadratic(int a, int b, int c, int x) {
    return add(multiply(a, multiply(x, x)), add(multiply(b, x), c));
}
