
#include <stdio.h>

int add_mul(int a, int b, int c, int d) {
    return (a + b) * (c - d);
}

int polynomial(int x) {
    return x * x * x + 3 * x * x + 2 * x + 1;
}

int chain_add(int a, int b, int c, int d, int e) {
    return a + b + c + d + e;
}

int abs_diff(int a, int b) {
    if (a > b) return a - b;
    return b - a;
}

int factorial(int n) {
    int result = 1;
    for (int i = 2; i <= n; i++)
        result = result * i;
    return result;
}

int fib(int n) {
    if (n <= 1) return n;
    int a = 0, b = 1;
    for (int i = 2; i <= n; i++) {
        int t = a + b;
        a = b;
        b = t;
    }
    return b;
}

int sum_squares(int n) {
    int sum = 0;
    for (int i = 1; i <= n; i++)
        sum = sum + i * i;
    return sum;
}

int nested_cond(int a, int b, int c) {
    if (a > 0) {
        if (b > 0) return a + b + c;
        else return a - b + c;
    } else {
        if (c > 0) return c - a - b;
        else return a + b - c;
    }
}

int bitwise_mix(int a, int b) {
    return (a & 0xff) | ((b << 8) ^ (a >> 2));
}

int multi_assign(int x) {
    int a = x + 1;
    int b = a + 2;
    int c = b + 3;
    int d = c + 4;
    return a + b + c + d;
}

int gcd(int a, int b) {
    while (b != 0) {
        int t = b;
        b = a % b;
        a = t;
    }
    return a;
}

int power(int base, int exp) {
    int result = 1;
    for (int i = 0; i < exp; i++)
        result = result * base;
    return result;
}

int collatz_steps(int n) {
    int steps = 0;
    while (n != 1) {
        if (n % 2 == 0)
            n = n / 2;
        else
            n = 3 * n + 1;
        steps = steps + 1;
    }
    return steps;
}

int matrix_trace(void) {
    int m[3][3] = {{1,2,3},{4,5,6},{7,8,9}};
    int trace = 0;
    for (int i = 0; i < 3; i++)
        trace = trace + m[i][i];
    return trace;
}

int selection_sort_sum(void) {
    int arr[] = {5, 3, 8, 1, 9, 2, 7, 4, 6, 0};
    int n = 10;
    for (int i = 0; i < n - 1; i++) {
        int min_idx = i;
        for (int j = i + 1; j < n; j++) {
            if (arr[j] < arr[min_idx])
                min_idx = j;
        }
        int tmp = arr[i];
        arr[i] = arr[min_idx];
        arr[min_idx] = tmp;
    }
    int sum = 0;
    for (int i = 0; i < n; i++)
        sum = sum + arr[i] * (i + 1);
    return sum;
}

int main(void) {
    printf("%d\n", add_mul(1, 2, 5, 3));
    printf("%d\n", polynomial(3));
    printf("%d\n", chain_add(1, 2, 3, 4, 5));
    printf("%d\n", abs_diff(10, 3));
    printf("%d\n", abs_diff(3, 10));
    printf("%d\n", factorial(6));
    printf("%d\n", fib(10));
    printf("%d\n", sum_squares(5));
    printf("%d\n", nested_cond(1, 2, 3));
    printf("%d\n", nested_cond(1, -2, 3));
    printf("%d\n", nested_cond(-1, 2, 3));
    printf("%d\n", nested_cond(-1, -2, -3));
    printf("%d\n", bitwise_mix(0xab, 0xcd));
    printf("%d\n", multi_assign(10));
    printf("%d\n", gcd(48, 18));
    printf("%d\n", power(2, 10));
    printf("%d\n", collatz_steps(27));
    printf("%d\n", matrix_trace());
    printf("%d\n", selection_sort_sum());
    return 0;
}
