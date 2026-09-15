#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

/* LLVMlite C Runtime */

extern int64_t program();

void ll_print_int(int64_t x) {
    printf("%ld\n", x);
}

int64_t* ll_alloc_array(int64_t size) {
    return (int64_t*)calloc((size_t)size, sizeof(int64_t));
}

int main() {
    int64_t result = program();
    return (int)(result & 0xFF);
}
