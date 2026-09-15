
#include "blockpool.h"
#include <stdlib.h>
#include <string.h>

typedef struct {
    int  block_id;
    int  ref_count;
    int *token_ids;
    int  num_tokens;
    int  capacity;
} Block;

struct BlockPool {
    Block *blocks;
    int   *free_stack;   /* stack of free block IDs                  */
    int    stack_top;    /* index past the top; also == num_free     */
    int    num_blocks;
    int    block_size;
};

/* ------------------------------------------------------------------ */
/*  Pool lifecycle                                                     */
/* ------------------------------------------------------------------ */

BlockPool *blockpool_create(int num_blocks, int block_size) {
    BlockPool *pool = (BlockPool *)malloc(sizeof(BlockPool));
    if (!pool) return NULL;

    pool->num_blocks = num_blocks;
    pool->block_size = block_size;
    pool->stack_top  = num_blocks;          /* all blocks start free */

    pool->blocks     = (Block *)malloc(num_blocks * sizeof(Block));
    pool->free_stack = (int *)malloc(num_blocks * sizeof(int));

    for (int i = 0; i < num_blocks; i++) {
        pool->blocks[i].block_id   = i;
        pool->blocks[i].ref_count  = 0;
        pool->blocks[i].token_ids  = (int *)calloc(block_size, sizeof(int));
        pool->blocks[i].num_tokens = 0;
        pool->blocks[i].capacity   = block_size;
        pool->free_stack[i]        = i;
    }

    return pool;
}

void blockpool_destroy(BlockPool *pool) {
    if (!pool) return;
    free(pool->blocks);
    free(pool->free_stack);
    free(pool);
}

/* ------------------------------------------------------------------ */
/*  Allocation / deallocation                                          */
/* ------------------------------------------------------------------ */

int blockpool_allocate(BlockPool *pool) {
    if (pool->stack_top <= 0) return -1;
    pool->stack_top--;
    int bid = pool->free_stack[pool->stack_top];
    pool->blocks[bid].ref_count  = 1;
    pool->blocks[bid].num_tokens = 0;
    memset(pool->blocks[bid].token_ids, 0,
           pool->block_size * sizeof(int));
    return bid;
}

void blockpool_free(BlockPool *pool, int block_id) {
    if (block_id < 0 || block_id >= pool->num_blocks) return;
    Block *b = &pool->blocks[block_id];
    b->ref_count--;
    if (b->ref_count <= 0) {
        b->ref_count  = 0;
        b->num_tokens = 0;
        memset(b->token_ids, 0, pool->block_size * sizeof(int));
        pool->free_stack[pool->stack_top] = block_id;
        pool->stack_top++;
    }
}

/* ------------------------------------------------------------------ */
/*  Reference counting                                                 */
/* ------------------------------------------------------------------ */

void blockpool_incref(BlockPool *pool, int block_id) {
    if (block_id < 0 || block_id >= pool->num_blocks) return;
    pool->blocks[block_id].ref_count++;
}

int blockpool_get_refcount(BlockPool *pool, int block_id) {
    if (block_id < 0 || block_id >= pool->num_blocks) return 0;
    return pool->blocks[block_id].ref_count;
}

/* ------------------------------------------------------------------ */
/*  Pool queries                                                       */
/* ------------------------------------------------------------------ */

int blockpool_num_free(BlockPool *pool)   { return pool->stack_top;  }
int blockpool_num_blocks(BlockPool *pool) { return pool->num_blocks; }
int blockpool_block_size(BlockPool *pool) { return pool->block_size; }

/* ------------------------------------------------------------------ */
/*  Token operations                                                   */
/* ------------------------------------------------------------------ */

void blockpool_set_token(BlockPool *pool, int block_id, int idx, int tok) {
    if (block_id < 0 || block_id >= pool->num_blocks) return;
    if (idx < 0 || idx >= pool->block_size) return;
    pool->blocks[block_id].token_ids[idx] = tok;
}

int blockpool_get_token(BlockPool *pool, int block_id, int idx) {
    if (block_id < 0 || block_id >= pool->num_blocks) return -1;
    if (idx < 0 || idx >= pool->block_size) return -1;
    return pool->blocks[block_id].token_ids[idx];
}

int blockpool_get_num_tokens(BlockPool *pool, int block_id) {
    if (block_id < 0 || block_id >= pool->num_blocks) return 0;
    return pool->blocks[block_id].num_tokens;
}

void blockpool_set_num_tokens(BlockPool *pool, int block_id, int count) {
    if (block_id < 0 || block_id >= pool->num_blocks) return;
    pool->blocks[block_id].num_tokens = count;
}

void blockpool_clear_tokens(BlockPool *pool, int block_id) {
    if (block_id < 0 || block_id >= pool->num_blocks) return;
    memset(pool->blocks[block_id].token_ids, 0,
           pool->block_size * sizeof(int));
    pool->blocks[block_id].num_tokens = 0;
}

void blockpool_copy_tokens(BlockPool *pool, int dst_id, int src_id) {
    if (dst_id < 0 || dst_id >= pool->num_blocks) return;
    if (src_id < 0 || src_id >= pool->num_blocks) return;
    memcpy(pool->blocks[dst_id].token_ids,
           pool->blocks[src_id].token_ids,
           pool->block_size * sizeof(int));
    pool->blocks[dst_id].num_tokens = pool->blocks[src_id].num_tokens;
}

void blockpool_append_token(BlockPool *pool, int block_id, int tok) {
    if (block_id < 0 || block_id >= pool->num_blocks) return;
    Block *b = &pool->blocks[block_id];
    if (b->num_tokens >= b->capacity) return;
    b->token_ids[b->num_tokens] = tok;
    b->num_tokens++;
}
