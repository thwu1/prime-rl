/* Probe: [[nodiscard]] standard attribute syntax (C23 feature) */
[[nodiscard]] int compute(void) { return 42; }
int main(void) {
    int result = compute();
    return (result == 42) ? 0 : 1;
}
