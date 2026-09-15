#include "canary.h"

bug_counter_t __magma_bugs[MAX_BUGS] = {{0}};
int __magma_bug_count = 0;
char *__magma_bug_names[MAX_BUGS] = {NULL};
const char *__magma_output_path = NULL;
