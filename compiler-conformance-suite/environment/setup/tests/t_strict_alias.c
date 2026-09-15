/* Test: type punning and aliasing — C99 6.5p7 */
#include "harness.h"

static int alias_store_load(int *ip, float *fp) {
    *ip = 42;
    *fp = 0.0f;
    return *ip;
}

int main(void) {
    TEST_INIT("strict aliasing C99 6.5p7");

    /* Non-aliased pointers: well-defined, must return 42 */
    int a;
    float b;
    TEST_VERIFY(alias_store_load(&a, &b) == 42);

    /* Aliased pointers via cast: strict aliasing violation.
       C99 6.5p7: "An object shall have its stored value accessed only
       by an lvalue expression that has one of the following types:"
       (list does not include float for int objects).
       Passing (float *)&storage makes fp alias ip with incompatible type.
       At -O0: float 0.0f bits (all zeros) overwrite int, read-back gives 0.
       At -O2: TBAA assumes int* and float* cannot alias, returns 42. */
    int storage;
    int (*volatile fn)(int *, float *) = alias_store_load;
    int result = fn(&storage, (float *)&storage);
    TEST_VERIFY(result == 0);

    TEST_RESULT();
}
