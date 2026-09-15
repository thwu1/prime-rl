/* Probe: typeof_unqual keyword for qualifier-stripped type deduction (C23 feature) */
int main(void) {
    const int ci = 42;
    typeof_unqual(ci) x = 10;
    x = 20;
    return (x == 20) ? 0 : 1;
}
