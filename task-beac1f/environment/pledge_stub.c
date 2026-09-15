/*
 * pledge.c - SECCOMP BPF pledge() implementation (stub)
 *
 */
#include "pledge.h"
#include <errno.h>

int pledge(const char *promises, const char *execpromises)
{
    (void)promises;
    (void)execpromises;
    /* TODO: Implement SECCOMP BPF pledge */
    errno = ENOSYS;
    return -1;
}
