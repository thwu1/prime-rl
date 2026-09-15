/*
 * accelq.h - Hardware Accelerator Queue Device Interface
 *
 * Userspace API for the /dev/accelq character device providing
 * access to hardware acceleration engines with asynchronous
 * job submission and DMA buffer management.
 *
 * SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note
 */

#ifndef _UAPI_LINUX_ACCELQ_H
#define _UAPI_LINUX_ACCELQ_H

#include <linux/ioctl.h>
#include <linux/types.h>

#define ACCELQ_MAGIC 'Q'

/* Context creation flags */
#define ACCELQ_CTX_SHARED       0x01
#define ACCELQ_CTX_EXCLUSIVE    0x02
#define ACCELQ_CTX_LOW_LATENCY  0x04

/* Queue creation flags */
#define ACCELQ_QUEUE_ORDERED    0x01
#define ACCELQ_QUEUE_PREEMPT    0x02

/* Job submission flags */
#define ACCELQ_SUBMIT_FENCE     0x01
#define ACCELQ_SUBMIT_SIGNAL    0x02
#define ACCELQ_SUBMIT_NO_WAIT   0x04

/* Wait flags */
#define ACCELQ_WAIT_TIMEOUT     0x01
#define ACCELQ_WAIT_ANY         0x02

/* Buffer mapping flags */
#define ACCELQ_BUF_READ         0x01
#define ACCELQ_BUF_WRITE        0x02
#define ACCELQ_BUF_COHERENT     0x04

/* Operation types for descriptors */
#define ACCELQ_OP_COPY          0x01
#define ACCELQ_OP_TRANSFORM     0x02
#define ACCELQ_OP_REDUCE        0x03
#define ACCELQ_OP_CUSTOM        0x04

/* Queue priority levels */
#define ACCELQ_PRIO_LOW         0
#define ACCELQ_PRIO_NORMAL      1
#define ACCELQ_PRIO_HIGH        2
#define ACCELQ_PRIO_REALTIME    3

/*
 * struct accelq_ctx_args - Context create/destroy arguments
 * @flags:      in: ACCELQ_CTX_* flags
 * @ctx_id:     out: context id
 * @max_queues: in: maximum number of queues for this context
 * @reserved:   must be 0
 */
struct accelq_ctx_args {
    __u32 flags;       /* in: ACCELQ_CTX_* flags */
    __u32 ctx_id;      /* out: context id */
    __u32 max_queues;  /* in: max number of queues */
    __u32 reserved;    /* must be 0 */
};

/*
 * struct accelq_queue_args - Queue create/destroy arguments
 * @ctx_id:    in: owning context id
 * @queue_id:  out: queue id
 * @flags:     in: ACCELQ_QUEUE_* flags
 * @ring_size: in: number of ring entries, power of 2, range [16,1024]
 */
struct accelq_queue_args {
    __u32 ctx_id;      /* in: context id */
    __u32 queue_id;    /* out: queue id */
    __u32 flags;       /* in: ACCELQ_QUEUE_* flags */
    __u32 ring_size;   /* in: power of 2, range [16, 1024] */
};

/*
 * struct accelq_descriptor - Single work descriptor
 * @op:         operation type (ACCELQ_OP_*)
 * @flags:      per-descriptor flags (ACCELQ_SUBMIT_*)
 * @src_handle: source buffer handle from ACCELQ_MAP_BUFFER
 * @dst_handle: destination buffer handle from ACCELQ_MAP_BUFFER
 * @src_len:    source data length in bytes
 * @dst_len:    destination data length in bytes
 * @params:     operation-specific parameters (opaque)
 */
struct accelq_descriptor {
    __u32 op;          /* ACCELQ_OP_* */
    __u32 flags;       /* ACCELQ_SUBMIT_* */
    __u64 src_handle;  /* source buffer handle */
    __u64 dst_handle;  /* destination buffer handle */
    __u32 src_len;     /* source length */
    __u32 dst_len;     /* destination length */
    __u8  params[32];  /* operation-specific parameters */
};

/*
 * struct accelq_submit_args - Job submission arguments
 * @ctx_id:    in: context id
 * @queue_id:  in: target queue id
 * @nr_descs:  in: number of descriptors in array
 * @flags:     in: ACCELQ_SUBMIT_* flags
 * @descs_ptr: in: userspace pointer to accelq_descriptor array
 * @job_id:    out: assigned job id for tracking
 * @reserved:  must be 0
 */
struct accelq_submit_args {
    __u32 ctx_id;      /* in: context id */
    __u32 queue_id;    /* in: queue id */
    __u32 nr_descs;    /* in: number of descriptors */
    __u32 flags;       /* in: ACCELQ_SUBMIT_* flags */
    __u64 descs_ptr;   /* in: pointer to accelq_descriptor array */
    __u32 job_id;      /* out: job id */
    __u32 reserved;    /* must be 0 */
};

/*
 * struct accelq_wait_args - Wait for job completion
 * @ctx_id:     in: context id
 * @job_id:     in: job to wait for
 * @flags:      in: ACCELQ_WAIT_* flags
 * @timeout_ms: in: timeout in milliseconds (0 = infinite)
 * @status:     out: completion status (0 = success, negative = error)
 * @reserved:   must be 0
 */
struct accelq_wait_args {
    __u32 ctx_id;      /* in: context id */
    __u32 job_id;      /* in: job to wait for */
    __u32 flags;       /* in: ACCELQ_WAIT_* flags */
    __u32 timeout_ms;  /* in: timeout in milliseconds */
    __s32 status;      /* out: completion status */
    __u32 reserved;    /* must be 0 */
};

/*
 * struct accelq_stats - Queue statistics (all output fields except ids)
 * @ctx_id:          in: context id
 * @queue_id:        in: queue id
 * @jobs_submitted:  out: total jobs submitted
 * @jobs_completed:  out: total jobs completed successfully
 * @jobs_failed:     out: total jobs that failed
 * @bytes_processed: out: total bytes processed
 */
struct accelq_stats {
    __u32 ctx_id;          /* in: context id */
    __u32 queue_id;        /* in: queue id */
    __u64 jobs_submitted;  /* out */
    __u64 jobs_completed;  /* out */
    __u64 jobs_failed;     /* out */
    __u64 bytes_processed; /* out */
};

/*
 * struct accelq_prio_args - Set queue priority
 * @ctx_id:   in: context id
 * @queue_id: in: queue id
 * @priority: in: ACCELQ_PRIO_* value
 * @reserved: must be 0
 */
struct accelq_prio_args {
    __u32 ctx_id;      /* in: context id */
    __u32 queue_id;    /* in: queue id */
    __u32 priority;    /* in: ACCELQ_PRIO_* */
    __u32 reserved;    /* must be 0 */
};

/*
 * struct accelq_buf_args - Buffer map/unmap arguments
 * @ctx_id: in: context id
 * @flags:  in: ACCELQ_BUF_* flags (for map)
 * @size:   in: buffer size in bytes
 * @handle: out for map, in for unmap: opaque buffer handle
 * @offset: out: mmap offset for userspace mapping
 */
struct accelq_buf_args {
    __u32 ctx_id;      /* in: context id */
    __u32 flags;       /* in: ACCELQ_BUF_* flags */
    __u64 size;        /* in: buffer size */
    __u64 handle;      /* out for map, in for unmap: buffer handle */
    __u64 offset;      /* out: mmap offset */
};

/* ioctl commands */
#define ACCELQ_CREATE_CTX    _IOWR(ACCELQ_MAGIC, 0x01, struct accelq_ctx_args)
#define ACCELQ_DESTROY_CTX   _IOW(ACCELQ_MAGIC, 0x02, struct accelq_ctx_args)
#define ACCELQ_CREATE_QUEUE  _IOWR(ACCELQ_MAGIC, 0x03, struct accelq_queue_args)
#define ACCELQ_DESTROY_QUEUE _IOW(ACCELQ_MAGIC, 0x04, struct accelq_queue_args)
#define ACCELQ_SUBMIT        _IOWR(ACCELQ_MAGIC, 0x10, struct accelq_submit_args)
#define ACCELQ_WAIT          _IOWR(ACCELQ_MAGIC, 0x11, struct accelq_wait_args)
#define ACCELQ_GET_STATS     _IOWR(ACCELQ_MAGIC, 0x20, struct accelq_stats)
#define ACCELQ_SET_PRIORITY  _IOW(ACCELQ_MAGIC, 0x21, struct accelq_prio_args)
#define ACCELQ_MAP_BUFFER    _IOWR(ACCELQ_MAGIC, 0x30, struct accelq_buf_args)
#define ACCELQ_UNMAP_BUFFER  _IOW(ACCELQ_MAGIC, 0x31, struct accelq_buf_args)

#endif /* _UAPI_LINUX_ACCELQ_H */
