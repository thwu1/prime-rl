/*
 * util.c - Cryptographic utility functions
 */

#include "secops.h"
#include <stdio.h>
#include <string.h>

/*
 * secops_cleanse - Securely zero memory.
 *
 * Uses volatile to prevent compiler from optimizing out the memset.
 */
void secops_cleanse(void *ptr, size_t len)
{
    volatile unsigned char *p = (volatile unsigned char *)ptr;

    while (len--)
        *p++ = 0;
}

/*
 * secops_rand_bytes - Fill buffer with random bytes.
 *
 * Returns 1 on success, 0 on failure.
 */
int secops_rand_bytes(unsigned char *buf, int len)
{
    FILE *fp;
    size_t nread;

    if (buf == NULL || len <= 0)
        return 0;

    fp = fopen("/dev/urandom", "rb");
    if (fp == NULL)
        return 0;

    nread = fread(buf, 1, (size_t)len, fp);
    fclose(fp);

    if ((int)nread != len)
        return 0;

    return 1;
}
