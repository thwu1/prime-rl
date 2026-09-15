/* PE analysis training sample - cross-compiled with MinGW for x86-64 Windows */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *MESSAGES[] = {
    "PE Analysis Training Sample",
    "Section mapping verification",
    "Relocation table exercise",
    "Import resolution check",
    "Memory dump reconstruction"
};

static int g_seed = 0xDEADBEEF;

typedef int (*op_func)(int, int);

static int op_add(int a, int b) { return a + b; }
static int op_sub(int a, int b) { return a - b; }
static int op_mul(int a, int b) { return a * b; }
static int op_xor(int a, int b) { return a ^ b; }

static op_func operations[] = {op_add, op_sub, op_mul, op_xor};
static const char *op_names[] = {"add", "sub", "mul", "xor"};

unsigned int hash_djb2(const char *s) {
    unsigned int h = 5381;
    while (*s) {
        h = ((h << 5) + h) ^ (unsigned char)*s++;
    }
    return h;
}

void run_operations(int a, int b) {
    int n = sizeof(operations) / sizeof(operations[0]);
    for (int i = 0; i < n; i++) {
        printf("  %s(%d, %d) = %d\n", op_names[i], a, b, operations[i](a, b));
    }
}

int main(int argc, char *argv[]) {
    int n_msgs = sizeof(MESSAGES) / sizeof(MESSAGES[0]);
    for (int i = 0; i < n_msgs; i++) {
        printf("[%d] %s (hash=0x%08x)\n", i, MESSAGES[i], hash_djb2(MESSAGES[i]));
    }

    printf("\nOperations with seed 0x%08x:\n", g_seed);
    run_operations(g_seed & 0xFF, (g_seed >> 8) & 0xFF);

    char *buf = (char *)malloc(128);
    if (buf) {
        int len = snprintf(buf, 128, "Result: 0x%08x", hash_djb2(MESSAGES[0]));
        printf("\n%s (len=%d)\n", buf, len);
        free(buf);
    }

    return 0;
}
