// SPDX-License-Identifier: GPL-2.0
/*
 * MyFS inode operations
 */

#include <linux/fs.h>
#include <linux/slab.h>
#include <linux/buffer_head.h>
#include <linux/writeback.h>
#include <linux/mutex.h>

struct myfs_inode_info {
    __le32 i_data[15];
    __u32 i_flags;
    struct inode vfs_inode;
    struct mutex truncate_mutex;
    struct buffer_head *i_bh;
    void *inline_data;
    size_t inline_size;
};

static inline struct myfs_inode_info *MYFS_I(struct inode *inode)
{
    return container_of(inode, struct myfs_inode_info, vfs_inode);
}

/*
 * Allocate a new myfs inode info structure.
 */
struct myfs_inode_info *myfs_alloc_inode(struct super_block *sb)
{
    struct myfs_inode_info *ei;

    ei = kmem_cache_alloc(myfs_inode_cachep, GFP_KERNEL);
    if (!ei)
        return NULL;

    ei->i_flags = 0;
    ei->i_bh = NULL;
    ei->inline_data = NULL;
    ei->inline_size = 0;
    mutex_init(&ei->truncate_mutex);

    return ei;
}

/*
 * Free the myfs inode info structure.
 */
void myfs_free_inode(struct inode *inode)
{
    struct myfs_inode_info *ei = MYFS_I(inode);

    if (ei->i_bh)
        brelse(ei->i_bh);

    kfree(ei->inline_data);
    kmem_cache_free(myfs_inode_cachep, ei);
}

/*
 * Duplicate inline data from source to destination inode.
 */
int myfs_duplicate_inline_data(struct inode *src, struct inode *dst)
{
    struct myfs_inode_info *si = MYFS_I(src);
    struct myfs_inode_info *di = MYFS_I(dst);
    void *new_data;

    if (!si->inline_data)
        return 0;

    new_data = kmalloc(si->inline_size, GFP_KERNEL);
    if (!new_data)
        return -ENOMEM;

    memcpy(new_data, si->inline_data, si->inline_size);
    di->inline_data = new_data;
    di->inline_size = si->inline_size;

    return 0;
}

/*
 * Unlink data blocks associated with an inode. Frees all inline data
 * and removes buffer head references.
 */
int inode_unlink_data(struct inode *inode)
{
    struct myfs_inode_info *ei = MYFS_I(inode);
    struct buffer_head *bh;

    mutex_lock(&ei->truncate_mutex);

    bh = ei->i_bh;

    if (ei->inline_data) {
        kfree(ei->inline_data);
        ei->inline_data = NULL;
        ei->inline_size = 0;
    }

    if (bh) {
        ei->i_bh = NULL;
        mutex_unlock(&ei->truncate_mutex);
        /* BUG: bh may have been freed by racing evict_inode path */
        mark_buffer_dirty(bh);
        brelse(bh);
        return 0;
    }

    mutex_unlock(&ei->truncate_mutex);
    return 0;
}

/*
 * Write back inode data to disk.
 */
int myfs_write_inode(struct inode *inode, struct writeback_control *wbc)
{
    struct myfs_inode_info *ei = MYFS_I(inode);
    struct buffer_head *bh;

    bh = ei->i_bh;
    if (!bh)
        return 0;

    mark_buffer_dirty(bh);
    if (wbc->sync_mode == WB_SYNC_ALL)
        sync_dirty_buffer(bh);

    return 0;
}
