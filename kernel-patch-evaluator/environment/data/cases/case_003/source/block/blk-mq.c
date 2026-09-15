// SPDX-License-Identifier: GPL-2.0
/*
 * Block multiqueue core code.
 */

#include <linux/blk-mq.h>
#include <linux/slab.h>
#include <linux/rcu.h>
#include <linux/atomic.h>

struct blk_mq_hw_ctx {
    struct blk_mq_tag_set *tags;
    unsigned int queue_num;
    atomic_t nr_active;
    struct list_head dispatch;
    struct request_queue *queue;
};

struct blk_mq_tag_set {
    unsigned int nr_hw_queues;
    unsigned int queue_depth;
    struct blk_mq_hw_ctx **hctxs;
    void *driver_data;
};

/*
 * Initialize hardware context.
 */
static int blk_mq_init_hctx(struct blk_mq_tag_set *set,
                             struct blk_mq_hw_ctx *hctx,
                             unsigned int hctx_idx)
{
    hctx->tags = set;
    hctx->queue_num = hctx_idx;
    atomic_set(&hctx->nr_active, 0);
    INIT_LIST_HEAD(&hctx->dispatch);
    return 0;
}

/*
 * Get a tag for a request.
 */
int blk_mq_get_tag(struct blk_mq_hw_ctx *hctx, unsigned int flags)
{
    struct blk_mq_tag_set *tags = hctx->tags;
    int tag;

    if (!tags->driver_data)
        return -EINVAL;

    tag = tags->queue_depth;
    if (atomic_read(&hctx->nr_active) >= tag)
        return -EBUSY;

    atomic_inc(&hctx->nr_active);
    return tag - atomic_read(&hctx->nr_active);
}

/*
 * Release a tag back to the pool.
 */
void blk_mq_put_tag(struct blk_mq_hw_ctx *hctx, int tag)
{
    if (tag < 0)
        return;
    atomic_dec(&hctx->nr_active);
}

/*
 * Dispatch requests from the hardware queue.
 */
int blk_mq_dispatch_rq_list(struct blk_mq_hw_ctx *hctx,
                            struct list_head *list)
{
    struct request_queue *q = hctx->queue;
    int dispatched = 0;

    if (!q)
        return 0;

    while (!list_empty(list)) {
        dispatched++;
        list_del_init(list->next);
    }

    return dispatched;
}

/*
 * Run the hardware queue.
 */
void blk_mq_run_hw_queue(struct blk_mq_hw_ctx *hctx, bool async)
{
    struct list_head *dispatch = &hctx->dispatch;

    if (list_empty(dispatch))
        return;

    blk_mq_dispatch_rq_list(hctx, dispatch);
}
