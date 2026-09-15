
#ifndef BLOCKPOOL_H
#define BLOCKPOOL_H

/*
 * BlockPool — low-level, reference-counted physical block pool
 * for the PagedAttention KV cache block manager.
 *
 * Each block holds up to block_size token IDs and maintains a
 * reference count for copy-on-write sharing.
 */

typedef struct BlockPool BlockPool;

/* Pool lifecycle */
BlockPool* blockpool_create(int num_blocks, int block_size);
void       blockpool_destroy(BlockPool *pool);

/* Block allocation */
int  blockpool_allocate(BlockPool *pool);
void blockpool_free(BlockPool *pool, int block_id);

/* Reference counting */
void blockpool_incref(BlockPool *pool, int block_id);
int  blockpool_get_refcount(BlockPool *pool, int block_id);

/* Pool queries */
int blockpool_num_free(BlockPool *pool);
int blockpool_num_blocks(BlockPool *pool);
int blockpool_block_size(BlockPool *pool);

/* Per-block token operations */
void blockpool_set_token(BlockPool *pool, int block_id, int index, int token);
int  blockpool_get_token(BlockPool *pool, int block_id, int index);
int  blockpool_get_num_tokens(BlockPool *pool, int block_id);
void blockpool_set_num_tokens(BlockPool *pool, int block_id, int count);
void blockpool_clear_tokens(BlockPool *pool, int block_id);
void blockpool_copy_tokens(BlockPool *pool, int dst_id, int src_id);
void blockpool_append_token(BlockPool *pool, int block_id, int token);

#endif /* BLOCKPOOL_H */
