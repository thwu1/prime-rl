#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern void foothold_function(void);

void pwnme(char *heap_buf) {
    char buf[32];
    memset(buf, 0, sizeof(buf));

    printf("The oracle bestows upon you a place to pivot: %p\n", heap_buf);

    puts("Stage 1 - send chain to heap buffer:");
    printf("> ");
    read(STDIN_FILENO, heap_buf, 0x100);

    puts("Stage 2 - send stack smash:");
    printf("> ");
    read(STDIN_FILENO, buf, 0x40);
}

__attribute__((used)) void uselessFunction(void) {
    foothold_function();
    exit(1);
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);

    puts("gauntlet by Unknown");
    puts("x86_64\n");

    char *heap = malloc(0x1000000);
    if (!heap) { perror("malloc"); exit(1); }
    char *pivot_target = heap + 0xffff00;

    pwnme(pivot_target);

    free(heap);
    puts("\nExiting");
    return 0;
}
