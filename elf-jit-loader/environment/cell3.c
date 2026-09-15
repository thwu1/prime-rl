extern int compute_sum(void);
extern int compute_product(void);
extern int add(int, int);
extern int quadratic(int, int, int, int);

int final_result(void) { return add(compute_sum(), compute_product()); }
int poly_eval(void) { return quadratic(2, 3, 5, 4); }
