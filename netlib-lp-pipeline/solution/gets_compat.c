/*
 * gets_compat.c - Provides gets() for modern glibc (2.34+) which removed it.
 *
 *
 * The Netlib emps.c decompressor (circa 1992) uses gets(), which was
 * removed from the C standard in C11 and from glibc in version 2.34.
 * This file provides a compatible replacement using fgets().
 */

#include <stdio.h>
#include <string.h>

char* gets(char* s) {
    if (!fgets(s, 4096, stdin))
        return NULL;
    /* Strip trailing newline that fgets keeps but gets did not */
    size_t len = strlen(s);
    if (len > 0 && s[len - 1] == '\n')
        s[len - 1] = '\0';
    return s;
}
