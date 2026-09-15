__declspec(dllexport) int add_numbers(int a, int b) {
    return a + b;
}

__declspec(dllexport) int multiply_numbers(int a, int b) {
    return a * b;
}

__declspec(dllexport) int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}
