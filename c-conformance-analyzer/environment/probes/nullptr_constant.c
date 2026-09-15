/* Probe: nullptr keyword for null pointer constant (C23 feature) */
#include <stddef.h>
int main(void) {
    int *p = nullptr;
    return (p == NULL) ? 0 : 1;
}
