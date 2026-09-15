#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern void foothold_function(void);

void uselessFunction(void) {
    foothold_function();
    exit(1);
}

void pwnme(char *pivot_dest) {
    char buf[32];
    memset(buf, 0, sizeof(buf));

    puts("Call ret2win() from libtarget");
    printf("Pivot destination: %p\n", pivot_dest);
    puts("Send chain to pivot, then smash the stack");
    printf("chain> ");
    read(STDIN_FILENO, pivot_dest, 256);

    printf("smash> ");
    read(STDIN_FILENO, buf, 96);
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);

    puts("pivot-ret2win by ROP Workshop\n");

    void *heap = malloc(0x1000000);
    void *pivot = (char *)heap + 0xffff00;
    pwnme(pivot);

    free(heap);
    puts("\nExiting");
    return 0;
}
