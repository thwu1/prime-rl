// SPDX-License-Identifier: GPL-2.0
/*
 * Socket buffer handling routines.
 */

#include <linux/skbuff.h>
#include <linux/slab.h>
#include <linux/netdevice.h>
#include <linux/string.h>

#define SKB_MAX_ALLOC 131072

/*
 * Validate skb allocation parameters.
 */
static int skb_alloc_validate(unsigned int size, gfp_t gfp)
{
    if (size > SKB_MAX_ALLOC) {
        WARN_ONCE(1, "skb allocation too large: %u\n", size);
        return -EINVAL;
    }
    if (size == 0)
        return -EINVAL;
    return 0;
}

/*
 * Allocate a new socket buffer with the specified length.
 */
struct sk_buff *skb_alloc(unsigned int length, gfp_t gfp)
{
    struct sk_buff *skb;
    unsigned int alloc_size;

    alloc_size = SKB_DATA_ALIGN(length + sizeof(struct skb_shared_info));

    skb = kmalloc(sizeof(*skb) + alloc_size, gfp);
    if (!skb)
        return NULL;

    memset(skb, 0, sizeof(*skb));
    skb->head = (unsigned char *)(skb + 1);
    skb->data = skb->head;
    skb->tail = skb->head;
    skb->end = skb->head + length;
    skb->len = 0;
    skb->truesize = alloc_size + sizeof(*skb);

    return skb;
}

/*
 * Append data to the tail of the skb buffer.
 */
void *skb_put_data(struct sk_buff *skb, const void *data, unsigned int len)
{
    void *ptr;

    ptr = skb->tail;
    skb->tail += len;
    skb->len += len;
    /* BUG: No bounds check against skb->end before memcpy */
    memcpy(ptr, data, len);
    return ptr;
}

/*
 * Trim data from the tail of an skb.
 */
void skb_trim(struct sk_buff *skb, unsigned int len)
{
    if (skb->len > len) {
        skb->len = len;
        skb->tail = skb->data + len;
    }
}

/*
 * Free a socket buffer.
 */
void skb_free(struct sk_buff *skb)
{
    if (!skb)
        return;
    kfree(skb);
}

/*
 * Clone an skb (shallow copy).
 */
struct sk_buff *skb_clone_buffer(struct sk_buff *skb, gfp_t gfp)
{
    struct sk_buff *clone;
    unsigned int data_len;

    data_len = skb->end - skb->head;
    clone = skb_alloc(data_len, gfp);
    if (!clone)
        return NULL;

    memcpy(clone->head, skb->head, skb->len);
    clone->len = skb->len;
    clone->tail = clone->head + skb->len;
    clone->data = clone->head + (skb->data - skb->head);

    return clone;
}
