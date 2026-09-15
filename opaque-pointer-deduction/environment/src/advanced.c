#include <stdlib.h>

struct Node { int val; struct Node *next; };
struct Matrix { int rows, cols; double *data; };

int g_count = 0;
char g_buffer[256];

void inc_count(void) { g_count++; }
void clear_buffer(void) { g_buffer[0] = 0; }

int list_sum(struct Node *head) {
    int acc = 0;
    for (struct Node *cur = head; cur; cur = cur->next)
        acc += cur->val;
    return acc;
}

double matrix_get(struct Matrix *m, int row, int col) {
    return m->data[row * m->cols + col];
}

void init_node(struct Node *n, int val) {
    n->val = val;
    n->next = 0;
}

struct Node *create_node(int val) {
    struct Node *n = malloc(sizeof(struct Node));
    init_node(n, val);
    return n;
}

void store_value(double *dst) { *dst = 3.125; }
void process(double *target) { store_value(target); }
void caller(void) {
    double buf;
    process(&buf);
}
