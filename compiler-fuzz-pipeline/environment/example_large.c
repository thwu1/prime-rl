
/*
 * Large C file for test case reduction exercise.
 * Produces different output when compiled with -O0 versus -O2.
 * Contains no undefined behavior.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define BUFFER_SIZE 1024
#define MAX_ITERATIONS 1000
#define HASH_SEED 0x811c9dc5u
#define GOLDEN_RATIO 0x9e3779b9u

typedef struct {
    int x;
    int y;
    unsigned int flags;
} point_t;

typedef struct {
    int data[16];
    int size;
    int capacity;
} small_vec_t;

static int fibonacci(int n) {
    if (n <= 1) return n;
    int a = 0, b = 1;
    for (int i = 2; i <= n; i++) {
        int t = a + b;
        a = b;
        b = t;
    }
    return b;
}

static void reverse_str(char *s) {
    int len = (int)strlen(s);
    for (int i = 0; i < len / 2; i++) {
        char t = s[i];
        s[i] = s[len - 1 - i];
        s[len - 1 - i] = t;
    }
}

static unsigned int fnv1a_hash(const char *s) {
    unsigned int h = HASH_SEED;
    while (*s) {
        h ^= (unsigned char)*s;
        h *= 0x01000193u;
        s++;
    }
    return h;
}

static void bubble_sort(int *a, int n) {
    for (int i = 0; i < n - 1; i++)
        for (int j = 0; j < n - i - 1; j++)
            if (a[j] > a[j + 1]) {
                int t = a[j];
                a[j] = a[j + 1];
                a[j + 1] = t;
            }
}

static int gcd(int a, int b) {
    while (b) {
        int t = b;
        b = a % b;
        a = t;
    }
    return a;
}

static int is_prime(int n) {
    if (n < 2) return 0;
    for (int i = 2; i * i <= n; i++)
        if (n % i == 0) return 0;
    return 1;
}

static int binary_search(int *a, int n, int x) {
    int lo = 0, hi = n - 1;
    while (lo <= hi) {
        int m = lo + (hi - lo) / 2;
        if (a[m] == x) return m;
        if (a[m] < x) lo = m + 1;
        else hi = m - 1;
    }
    return -1;
}

static long mod_pow(long base, int exp, long mod) {
    long result = 1;
    base %= mod;
    while (exp > 0) {
        if (exp % 2 == 1)
            result = (result * base) % mod;
        exp /= 2;
        base = (base * base) % mod;
    }
    return result;
}

static int collatz_length(int n) {
    int steps = 0;
    while (n != 1 && n > 0) {
        if (n % 2 == 0) n /= 2;
        else n = 3 * n + 1;
        steps++;
    }
    return steps;
}

static int popcount_u32(unsigned int x) {
    int c = 0;
    while (x) {
        c += x & 1;
        x >>= 1;
    }
    return c;
}

static void matrix_multiply_4x4(int a[4][4], int b[4][4], int c[4][4]) {
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) {
            c[i][j] = 0;
            for (int k = 0; k < 4; k++)
                c[i][j] += a[i][k] * b[k][j];
        }
}

static unsigned int crc32_byte(unsigned int crc, unsigned char byte) {
    crc ^= byte;
    for (int j = 0; j < 8; j++) {
        if (crc & 1u)
            crc = (crc >> 1) ^ 0xEDB88320u;
        else
            crc >>= 1;
    }
    return crc;
}

static void insertion_sort(int *a, int n) {
    for (int i = 1; i < n; i++) {
        int key = a[i], j = i - 1;
        while (j >= 0 && a[j] > key) {
            a[j + 1] = a[j];
            j--;
        }
        a[j + 1] = key;
    }
}

static int digit_sum(int n) {
    int s = 0;
    if (n < 0) n = -n;
    while (n > 0) {
        s += n % 10;
        n /= 10;
    }
    return s;
}

static unsigned int rotate_left(unsigned int val, int shift) {
    shift &= 31;
    if (shift == 0) return val;
    return (val << shift) | (val >> (32 - shift));
}

static int array_max(int *a, int n) {
    int mx = a[0];
    for (int i = 1; i < n; i++)
        if (a[i] > mx) mx = a[i];
    return mx;
}

static int array_min(int *a, int n) {
    int mn = a[0];
    for (int i = 1; i < n; i++)
        if (a[i] < mn) mn = a[i];
    return mn;
}

static int levenshtein(const char *s, const char *t) {
    int m = (int)strlen(s), n = (int)strlen(t);
    if (m > 64 || n > 64) return -1;
    int d[65][65];
    for (int i = 0; i <= m; i++) d[i][0] = i;
    for (int j = 0; j <= n; j++) d[0][j] = j;
    for (int i = 1; i <= m; i++)
        for (int j = 1; j <= n; j++) {
            int cost = (s[i-1] == t[j-1]) ? 0 : 1;
            int a = d[i-1][j] + 1;
            int b = d[i][j-1] + 1;
            int c = d[i-1][j-1] + cost;
            d[i][j] = a < b ? (a < c ? a : c) : (b < c ? b : c);
        }
    return d[m][n];
}

static void fill_sieve(int *sieve, int limit) {
    for (int i = 0; i < limit; i++) sieve[i] = 1;
    sieve[0] = sieve[1] = 0;
    for (int i = 2; i * i < limit; i++)
        if (sieve[i])
            for (int j = i * i; j < limit; j += i)
                sieve[j] = 0;
}

int main(void) {
#ifdef __OPTIMIZE__
    printf("optimized\n");
#else
    printf("baseline\n");
#endif
    return 0;
}
