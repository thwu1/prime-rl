int alloc_a(int size) {
    return size;
}

int alloc_b(int size) {
    return size;
}

int alloc_c(int size) {
    return size;
}

int setup(void) {
    int a;
    int b;
    int c;
    a = alloc_a(10);
    b = alloc_b(20);
    c = alloc_c(30);
    return a + b + c;
}

void cleanup(void) {
}
