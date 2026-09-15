/* Probe: sizeof(true) reflecting type change from int to bool across standards */
#include <stdbool.h>
#include <stdio.h>
int main(void) {
    printf("%zu\n", sizeof(true));
    return 0;
}
