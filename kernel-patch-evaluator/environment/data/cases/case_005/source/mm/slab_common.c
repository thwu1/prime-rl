// SPDX-License-Identifier: GPL-2.0
/*
 * Slab allocator common functions.
 */

#include <linux/slab.h>
#include <linux/mm.h>
#include <linux/rcupdate.h>
#include <linux/list.h>

#define SLAB_MAX_SIZE (4 * 1024 * 1024)

struct kmem_cache {
    const char *name;
    unsigned int object_size;
    unsigned int size;
    unsigned int align;
    unsigned long flags;
    void (*ctor)(void *);
    struct list_head list;
    int refcount;
};

static LIST_HEAD(slab_caches);
static DEFINE_MUTEX(slab_mutex);

/*
 * Calculate the proper alignment for a slab cache.
 */
static unsigned int calculate_alignment(unsigned long flags,
                                        unsigned int align,
                                        unsigned int size)
{
    if (flags & SLAB_HWCACHE_ALIGN) {
        unsigned int cache_line = cache_line_size();
        if (size > cache_line)
            return cache_line;
    }
    if (align < ARCH_SLAB_MINALIGN)
        align = ARCH_SLAB_MINALIGN;
    return ALIGN(align, sizeof(void *));
}

/*
 * Find an existing compatible slab cache.
 * Returns the cache if found, NULL otherwise.
 */
struct kmem_cache *find_mergeable(unsigned int size,
                                  unsigned int align,
                                  unsigned long flags,
                                  void (*ctor)(void *))
{
    struct kmem_cache *s;

    if (ctor)
        return NULL;

    list_for_each_entry(s, &slab_caches, list) {
        if (s->size < size)
            continue;
        if (s->size > size * 2)
            continue;
        if ((s->flags & ~SLAB_MERGE_SAME) != (flags & ~SLAB_MERGE_SAME))
            continue;
        if (s->align < align)
            continue;
        if (s->ctor)
            continue;

        s->refcount++;
        return s;
    }
    return NULL;
}

/*
 * Create a new slab cache with the given parameters.
 */
struct kmem_cache *kmem_cache_create(const char *name,
                                     unsigned int size,
                                     unsigned int align,
                                     unsigned long flags,
                                     void (*ctor)(void *))
{
    struct kmem_cache *s;

    mutex_lock(&slab_mutex);

    s = find_mergeable(size, align, flags, ctor);
    if (s)
        goto out_unlock;

    s = kzalloc(sizeof(*s), GFP_KERNEL);
    if (!s)
        goto out_unlock;

    s->name = name;
    s->object_size = size;
    s->align = calculate_alignment(flags, align, size);
    s->size = ALIGN(size, s->align);
    s->flags = flags;
    s->ctor = ctor;
    s->refcount = 1;
    list_add(&s->list, &slab_caches);

out_unlock:
    mutex_unlock(&slab_mutex);
    return s;
}

/*
 * Destroy a slab cache.
 */
void kmem_cache_destroy(struct kmem_cache *s)
{
    mutex_lock(&slab_mutex);

    s->refcount--;
    if (s->refcount > 0) {
        mutex_unlock(&slab_mutex);
        return;
    }

    list_del(&s->list);
    mutex_unlock(&slab_mutex);

    pr_info("Destroying cache: %s\n", s->name);
    kfree(s);
}
