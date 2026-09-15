/*
 * mini_gc.h - Conservative mark-sweep garbage collector API.
 */
#ifndef MINI_GC_H
#define MINI_GC_H

#include <stddef.h>

/* Initialize the collector with the given heap size (bytes). */
int gc_init(size_t heap_size);

/* Allocate GC-managed memory (may contain traceable pointers). */
void *gc_malloc(size_t size);

/* Allocate pointer-free (atomic) memory; contents will not be scanned. */
void *gc_malloc_atomic(size_t size);

/* Force a garbage collection cycle. */
void gc_collect(void);

/* Finalizer callback signature. */
typedef void (*gc_finalizer_fn)(void *obj, void *client_data);

/* Register a one-shot finalizer for obj.  Returns 0 on success. */
int gc_register_finalizer(void *obj, gc_finalizer_fn fn, void *client_data);

/* Register a disappearing link: *link is set to NULL when its target
   becomes unreachable.  Returns 0 on success. */
int gc_register_disappearing_link(void **link);

/* Unregister a previously registered disappearing link. */
int gc_unregister_disappearing_link(void **link);

/* Add a root scanning range [start, end). */
int gc_add_root(void *start, void *end);

/* Statistics. */
size_t gc_collection_count(void);
size_t gc_heap_size(void);
size_t gc_free_bytes(void);

/* Release the heap. */
void gc_shutdown(void);

#endif /* MINI_GC_H */
