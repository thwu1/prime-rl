#ifndef WALLOC_NATIVE_H
#define WALLOC_NATIVE_H

#include <stddef.h>

void   walloc_init(void);
void  *walloc_malloc(size_t size);
void   walloc_free(void *ptr);
void  *walloc_realloc(void *ptr, size_t new_size);
size_t walloc_malloc_usable_size(void *ptr);

#endif /* WALLOC_NATIVE_H */
