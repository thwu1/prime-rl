#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    char *s = (char *)malloc(128);
    strcpy(s, "hello");
    printf("%s world\n", s);
    int n = atoi("42");
    fprintf(stderr, "%d\n", n);
    free(s);
    return 0;
}
