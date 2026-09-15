/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
/*
 * UAPI header for /dev/dmabuf_mgr - DMA buffer management device
 *
 * Copyright (C) 2024 Example Corp.
 */
#ifndef _UAPI_LINUX_DMABUF_MGR_H
#define _UAPI_LINUX_DMABUF_MGR_H

#include <linux/ioctl.h>
#include <linux/types.h>

#define DMABUF_MGR_MAGIC 'D'

/* Buffer access flags - used in create/map operations */
#define DMABUF_FLAG_READ      0x01
#define DMABUF_FLAG_WRITE     0x02
#define DMABUF_FLAG_EXEC      0x04
#define DMABUF_FLAG_COHERENT  0x08
#define DMABUF_FLAG_CACHED    0x10

/* Sync operation flags - used in sync operations only */
#define DMABUF_SYNC_READ      0x01
#define DMABUF_SYNC_WRITE     0x02
#define DMABUF_SYNC_START     0x04
#define DMABUF_SYNC_END       0x08

/* Memory types */
#define DMABUF_MEM_TYPE_SYSTEM    0
#define DMABUF_MEM_TYPE_DEVICE    1
#define DMABUF_MEM_TYPE_COHERENT  2

/* Transfer directions */
#define DMABUF_XFER_TO_DEVICE     0
#define DMABUF_XFER_FROM_DEVICE   1
#define DMABUF_XFER_BIDIRECTIONAL 2

/* Max scatter-gather entries */
#define DMABUF_MAX_SG_ENTRIES 64

/*
 * Buffer handle type - 32-bit unsigned integer.
 * Returned by CREATE, consumed by DESTROY, MAP, SYNC, TRANSFER, QUERY.
 */
typedef __u32 dmabuf_handle_t;

/*
 * Scatter-gather entry.
 * Wire format: addr (8 bytes), length (4 bytes), flags (4 bytes).
 */
struct dmabuf_sg_entry {
    __u64 addr;        /* physical address */
    __u32 length;      /* segment length in bytes */
    __u32 flags;       /* per-entry flags (subset of DMABUF_FLAG_*) */
};

/*
 * Create buffer request.
 * The 'handle' field is written by the kernel on success (output).
 * The 'padding' field must be set to zero.
 */
struct dmabuf_create_req {
    __u64 size;                /* input: requested buffer size */
    __u32 flags;               /* input: DMABUF_FLAG_* */
    __u32 mem_type;            /* input: DMABUF_MEM_TYPE_* */
    __u32 alignment;           /* input: required alignment, power of 2 */
    __u32 padding;             /* must be zero */
    dmabuf_handle_t handle;    /* output: allocated buffer handle */
};

/*
 * Map buffer into userspace.
 * The 'vaddr' field is written by the kernel (output).
 */
struct dmabuf_map_req {
    dmabuf_handle_t handle;    /* input: buffer handle */
    __u32 flags;               /* input: mapping flags (DMABUF_FLAG_*) */
    __u64 offset;              /* input: offset within buffer */
    __u64 length;              /* input: map length (0 = entire buffer) */
    __u64 vaddr;               /* output: mapped virtual address */
};

/*
 * Synchronize buffer cache.
 * All fields are input.
 */
struct dmabuf_sync_req {
    dmabuf_handle_t handle;    /* input: buffer handle */
    __u32 flags;               /* input: DMABUF_SYNC_* flags */
    __u64 offset;              /* input: offset within buffer */
    __u64 length;              /* input: length to sync */
};

/*
 * Transfer data between two buffers.
 * The 'padding' field must be set to zero.
 */
struct dmabuf_transfer_req {
    dmabuf_handle_t src_handle;  /* input: source buffer handle */
    dmabuf_handle_t dst_handle;  /* input: destination buffer handle */
    __u64 src_offset;            /* input: offset in source */
    __u64 dst_offset;            /* input: offset in destination */
    __u64 length;                /* input: bytes to transfer */
    __u32 direction;             /* input: DMABUF_XFER_* */
    __u32 padding;               /* must be zero */
};

/*
 * Query buffer information.
 * The 'handle' field is input; all other fields are output.
 * 'sg_count' indicates how many entries in sg_entries[] are valid.
 */
struct dmabuf_query_resp {
    dmabuf_handle_t handle;    /* input: buffer handle to query */
    __u32 flags;               /* output: buffer flags */
    __u64 size;                /* output: buffer size */
    __u32 mem_type;            /* output: memory type */
    __u32 refcount;            /* output: reference count */
    __u32 sg_count;            /* output: number of valid SG entries */
    __u32 padding;
    struct dmabuf_sg_entry sg_entries[DMABUF_MAX_SG_ENTRIES]; /* output */
};

/*
 * Batch operation header.
 * op_type selects the operation: 0=sync, 1=transfer.
 */
struct dmabuf_batch_hdr {
    __u32 num_ops;             /* number of operations in batch */
    __u32 flags;               /* batch-level flags */
    __u32 op_type;             /* 0 = sync, 1 = transfer */
};

/*
 * Batch operation - packed struct with variable-length trailing array.
 * The union discriminated by header.op_type.
 */
struct dmabuf_batch_op {
    struct dmabuf_batch_hdr header;
    union {
        struct dmabuf_sync_req sync_ops[0];
        struct dmabuf_transfer_req xfer_ops[0];
    };
} __attribute__((packed));

/* ioctl commands */
#define DMABUF_IOC_CREATE    _IOWR(DMABUF_MGR_MAGIC, 0x01, struct dmabuf_create_req)
#define DMABUF_IOC_DESTROY   _IOW(DMABUF_MGR_MAGIC, 0x02, dmabuf_handle_t)
#define DMABUF_IOC_MAP       _IOWR(DMABUF_MGR_MAGIC, 0x03, struct dmabuf_map_req)
#define DMABUF_IOC_UNMAP     _IOW(DMABUF_MGR_MAGIC, 0x04, struct dmabuf_map_req)
#define DMABUF_IOC_SYNC      _IOW(DMABUF_MGR_MAGIC, 0x05, struct dmabuf_sync_req)
#define DMABUF_IOC_TRANSFER  _IOW(DMABUF_MGR_MAGIC, 0x06, struct dmabuf_transfer_req)
#define DMABUF_IOC_QUERY     _IOWR(DMABUF_MGR_MAGIC, 0x07, struct dmabuf_query_resp)
#define DMABUF_IOC_BATCH     _IOW(DMABUF_MGR_MAGIC, 0x08, struct dmabuf_batch_op)

#endif /* _UAPI_LINUX_DMABUF_MGR_H */
