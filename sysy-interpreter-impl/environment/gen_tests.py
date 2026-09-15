#!/usr/bin/env python3
"""Generate SysY test programs for /app/tests/."""
import os

os.makedirs('/app/tests', exist_ok=True)

TESTS = {}

TESTS['test_00_basic_return.sy'] = '''\
int main() {
    return 42;
}
'''

TESTS['test_01_arithmetic.sy'] = '''\
int main() {
    putint(2 + 3 * 4);
    putch(10);
    putint((2 + 3) * 4);
    putch(10);
    putint(10 / 3);
    putch(10);
    putint(10 % 3);
    putch(10);
    return 0;
}
'''

TESTS['test_02_if_else.sy'] = '''\
int main() {
    int x = 10;
    if (x > 5) {
        putint(1);
    } else {
        putint(0);
    }
    putch(10);
    if (x < 5) {
        putint(1);
    } else {
        putint(0);
    }
    putch(10);
    return 0;
}
'''

TESTS['test_03_while_loop.sy'] = '''\
int main() {
    int i = 0;
    int sum = 0;
    while (i < 10) {
        sum = sum + i;
        i = i + 1;
    }
    putint(sum);
    putch(10);
    return 0;
}
'''

TESTS['test_04_recursion.sy'] = '''\
int gcd(int a, int b) {
    if (b == 0) return a;
    return gcd(b, a % b);
}

int main() {
    putint(gcd(36, 24));
    putch(10);
    return 0;
}
'''

TESTS['test_05_array_init_2d.sy'] = '''\
int main() {
    int a[3][2] = {1, 2, {3}, {5}};
    int i = 0;
    while (i < 3) {
        int j = 0;
        while (j < 2) {
            putint(a[i][j]);
            putch(32);
            j = j + 1;
        }
        i = i + 1;
    }
    putch(10);
    return 0;
}
'''

TESTS['test_06_short_circuit.sy'] = '''\
int x;

int inc() {
    x = x + 1;
    return x;
}

int main() {
    x = 0;
    if (1 || inc()) {}
    putint(x);
    putch(10);

    if (0 && inc()) {}
    putint(x);
    putch(10);

    if (0 || inc()) {}
    putint(x);
    putch(10);

    if (1 && inc()) {}
    putint(x);
    putch(10);

    return 0;
}
'''

TESTS['test_07_scoping.sy'] = '''\
int a;

int main() {
    a = 1;
    putint(a);
    putch(10);
    int a = 2;
    putint(a);
    putch(10);
    {
        int a = 3;
        putint(a);
        putch(10);
    }
    putint(a);
    putch(10);
    return 0;
}
'''

TESTS['test_08_array_param.sy'] = '''\
void fill(int arr[], int n) {
    int i = 0;
    while (i < n) {
        arr[i] = i * i;
        i = i + 1;
    }
}

int main() {
    int a[5] = {};
    fill(a, 5);
    int i = 0;
    while (i < 5) {
        putint(a[i]);
        putch(32);
        i = i + 1;
    }
    putch(10);
    return 0;
}
'''

TESTS['test_09_break_continue.sy'] = '''\
int main() {
    int i = 0;
    int sum = 0;
    while (i < 20) {
        i = i + 1;
        if (i % 2 == 0) {
            continue;
        }
        if (i > 10) {
            break;
        }
        sum = sum + i;
    }
    putint(sum);
    putch(10);
    return 0;
}
'''

TESTS['test_10_hex_octal.sy'] = '''\
int main() {
    int a = 0x1A;
    int b = 032;
    int c = 26;
    putint(a);
    putch(32);
    putint(b);
    putch(32);
    putint(c);
    putch(10);
    return 0;
}
'''

TESTS['test_11_fibonacci.sy'] = '''\
int fib(int n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}

int main() {
    int i = 0;
    while (i < 10) {
        putint(fib(i));
        putch(32);
        i = i + 1;
    }
    putch(10);
    return 0;
}
'''

TESTS['test_12_unary_ops.sy'] = '''\
int main() {
    int a = 5;
    putint(-a);
    putch(10);
    putint(+a);
    putch(10);
    putint(!a);
    putch(10);
    putint(!0);
    putch(10);
    putint(!!5);
    putch(10);
    return 0;
}
'''

TESTS['test_13_neg_div_mod.sy'] = '''\
int main() {
    putint(-7 / 2);
    putch(10);
    putint(-7 % 2);
    putch(10);
    putint(7 / -2);
    putch(10);
    putint(7 % -2);
    putch(10);
    return 0;
}
'''

TESTS['test_14_prime_count.sy'] = '''\
int main() {
    int count = 0;
    int i = 2;
    while (i < 100) {
        int j = 2;
        int is_prime = 1;
        while (j * j <= i) {
            if (i % j == 0) {
                is_prime = 0;
                break;
            }
            j = j + 1;
        }
        if (is_prime) {
            count = count + 1;
        }
        i = i + 1;
    }
    putint(count);
    putch(10);
    return 0;
}
'''

TESTS['test_15_const_array_dim.sy'] = '''\
const int N = 5;
const int M = N * 2 + 1;

int main() {
    int arr[M];
    int i = 0;
    while (i < M) {
        arr[i] = i * i;
        i = i + 1;
    }
    putint(arr[M - 1]);
    putch(10);
    putint(M);
    putch(10);
    return 0;
}
'''

TESTS['test_16_array_init_complex.sy'] = '''\
int main() {
    int a[4][2] = {{}, {3, 4}, 5, 6};
    int i = 0;
    while (i < 4) {
        int j = 0;
        while (j < 2) {
            putint(a[i][j]);
            putch(32);
            j = j + 1;
        }
        i = i + 1;
    }
    putch(10);
    return 0;
}
'''

TESTS['test_17_void_func.sy'] = '''\
void print_range(int start, int end) {
    int i = start;
    while (i < end) {
        putint(i);
        putch(32);
        i = i + 1;
    }
    putch(10);
    return;
}

int main() {
    print_range(1, 6);
    print_range(10, 13);
    return 0;
}
'''

TESTS['test_18_matrix_param.sy'] = '''\
void print_mat(int m[][3], int rows) {
    int i = 0;
    while (i < rows) {
        int j = 0;
        while (j < 3) {
            putint(m[i][j]);
            putch(32);
            j = j + 1;
        }
        putch(10);
        i = i + 1;
    }
}

int main() {
    int mat[2][3] = {{1, 2, 3}, {4, 5, 6}};
    print_mat(mat, 2);
    return 0;
}
'''

TESTS['test_19_global_init.sy'] = '''\
int g[5];

int main() {
    int i = 0;
    while (i < 5) {
        putint(g[i]);
        putch(32);
        i = i + 1;
    }
    putch(10);
    g[2] = 42;
    putint(g[2]);
    putch(10);
    return 0;
}
'''

TESTS['test_20_large_return.sy'] = '''\
int main() {
    return 300;
}
'''

TESTS['test_21_const_array.sy'] = '''\
int main() {
    const int a[3] = {10, 20, 30};
    int sum = a[0] + a[1] + a[2];
    putint(sum);
    putch(10);
    return 0;
}
'''

TESTS['test_22_scope_array_func.sy'] = '''\
int sum(int a[], int n) {
    int s = 0;
    int i = 0;
    while (i < n) {
        s = s + a[i];
        i = i + 1;
    }
    return s;
}

int main() {
    int a[5] = {1, 2, 3, 4, 5};
    putint(sum(a, 5));
    putch(10);
    {
        int a[3] = {10, 20, 30};
        putint(sum(a, 3));
        putch(10);
    }
    putint(sum(a, 5));
    putch(10);
    return 0;
}
'''

for name, content in TESTS.items():
    with open(f'/app/tests/{name}', 'w') as f:
        f.write(content)

print(f"Generated {len(TESTS)} test programs in /app/tests/")
