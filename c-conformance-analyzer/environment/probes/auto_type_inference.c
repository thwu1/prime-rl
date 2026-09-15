/* Probe: auto type inference for variable declarations (C23 feature) */
int main(void) {
    auto x = 42;
    return (x == 42) ? 0 : 1;
}
