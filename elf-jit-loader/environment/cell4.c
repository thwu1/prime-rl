extern int add(int, int);

static int counter;

int increment(void) {
    counter = add(counter, 1);
    return counter;
}

int get_counter(void) {
    return counter;
}
