/*
 * ptysession - PTY session manager (stub — implement this)
 * Usage: ptysession <command> [args...]
 *
 * This program should allocate a pseudoterminal pair, fork a child
 * into a new session backed by the PTY slave, and relay I/O between
 * the parent's file descriptors and the PTY master.
 */
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s command [args...]\n", argv[0]);
        return 1;
    }
    fprintf(stderr, "ptysession: not implemented\n");
    return 1;
}
