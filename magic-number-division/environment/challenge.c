#include <stdio.h>
#include <stdlib.h>

__attribute__((noinline)) int func0(int x) { return x / 7; }
__attribute__((noinline)) int func1(int x) { return (int)((unsigned)x / 10u); }
__attribute__((noinline)) unsigned func2(unsigned x) { return x % 17; }
__attribute__((noinline)) int func3(int x) { return x / 6; }
__attribute__((noinline)) int func4(int x) { return x / 127; }
__attribute__((noinline)) unsigned func5(unsigned x) { return x / 641; }
__attribute__((noinline)) int func6(int x) { return x / 7; }
__attribute__((noinline)) unsigned func7(unsigned x) { return x / 31337; }

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <func_index> <value>\n", argv[0]);
        return 1;
    }
    int idx = atoi(argv[1]);
    long long val = atoll(argv[2]);
    switch (idx) {
        case 0: printf("%d\n", func0((int)val)); break;
        case 1: printf("%d\n", func1((int)val)); break;
        case 2: printf("%u\n", func2((unsigned)val)); break;
        case 3: printf("%d\n", func3((int)val)); break;
        case 4: printf("%d\n", func4((int)val)); break;
        case 5: printf("%u\n", func5((unsigned)val)); break;
        case 6: printf("%d\n", func6((int)val)); break;
        case 7: printf("%u\n", func7((unsigned)val)); break;
        default: fprintf(stderr, "Unknown function index\n"); return 1;
    }
    return 0;
}
