// SPDX-License-Identifier: GPL-2.0
#include <linux/sched.h>
#include <linux/kernel.h>

struct load_weight {
    unsigned long weight;
    u32 inv_weight;
};

struct cfs_rq {
    struct load_weight load;
    unsigned long nr_running;
    u64 min_vruntime;
};

static u64 calc_delta_fair(u64 delta, struct cfs_rq *cfs_rq)
{
    if (!cfs_rq->load.weight)
        return delta;
    return delta * 1024 / cfs_rq->load.weight;
}

int update_load_avg(struct cfs_rq *cfs_rq, u64 now)
{
    u64 delta, load;

    delta = now - cfs_rq->min_vruntime;
    load = cfs_rq->load.weight;

    if (delta > 1000000000ULL)
        delta = 1000000000ULL;

    cfs_rq->min_vruntime = now;
    return calc_delta_fair(delta, cfs_rq) > 0 ? 1 : 0;
}
