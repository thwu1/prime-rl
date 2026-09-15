#include <stdint.h>
#include <stddef.h>

struct Tree { int val; struct Tree *left, *right; };
struct Pair { int64_t a, b; };
struct Tagged { int tag; double data[4]; };

int tree_depth(struct Tree *node) {
    if (!node) return 0;
    int ld = tree_depth(node->left);
    int rd = tree_depth(node->right);
    return (ld > rd ? ld : rd) + 1;
}

double tagged_get(struct Tagged *t, int idx) {
    return t->data[idx];
}

int64_t pair_sum_array(void) {
    struct Pair pairs[10];
    return pairs[0].a + pairs[0].b;
}

int conditional_load(int *a, int *b, int cond) {
    int *chosen = cond ? a : b;
    return *chosen;
}
