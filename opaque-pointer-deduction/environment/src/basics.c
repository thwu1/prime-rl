#include <stdint.h>

struct Point { double x, y; };
struct Rect { struct Point origin, corner; };
struct Color { uint8_t r, g, b, a; };

int scalar_ops(void) {
    int x = 42;
    long long y = 100;
    float f = 3.14f;
    return x + (int)y + (int)f;
}

double point_get_x(struct Point *p) {
    return p->x;
}

void point_set(struct Point *p, double x, double y) {
    p->x = x;
    p->y = y;
}

double rect_origin_x(struct Rect *r) {
    return r->origin.x;
}

void rect_set_corner(struct Rect *r, double x, double y) {
    r->corner.x = x;
    r->corner.y = y;
}

int array_sum(int *arr, int n) {
    int s = 0;
    for (int i = 0; i < n; i++)
        s += arr[i];
    return s;
}

int deref_pp(int **pp) {
    int *p = *pp;
    return *p;
}

uint8_t get_alpha(struct Color *c) {
    return c->a;
}

double *rect_origin_ptr(struct Rect *r) {
    return &r->origin.x;
}

double *rect_corner_y_ptr(struct Rect *r) {
    return &r->corner.y;
}
