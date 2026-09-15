/* Probe: typeof keyword (C23 standard keyword, GNU extension in C11/C17) */
int main(void) {
    int x = 42;
    typeof(x) y = x + 1;
    return (y == 43) ? 0 : 1;
}
