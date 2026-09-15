#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

extern int64_t _program(int64_t argc, char** argv);

void _print_int(int64_t x) {
    printf("%ld\n", x);
}

void _print_string(char* s) {
    printf("%s\n", s);
}

int64_t* _alloc_array(int64_t size) {
    return (int64_t*)calloc(size, sizeof(int64_t));
}

int main(int argc, char** argv) {
    int64_t result = _program((int64_t)argc, argv);
    printf("%ld\n", result);
    return 0;
}
