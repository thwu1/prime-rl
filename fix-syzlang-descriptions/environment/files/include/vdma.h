/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
/*
 * UAPI header for /dev/vdma - Virtual DMA Controller
 *
 * Provides channel-based DMA transfer management with scatter-gather,
 * fencing, batch submission, and asynchronous event notification.
 *
 * Copyright (C) 2024 Example Corp.
 */
#ifndef _UAPI_LINUX_VDMA_H
#define _UAPI_LINUX_VDMA_H

#include <linux/ioctl.h>
#include <linux/types.h>

#define VDMA_MAGIC 'V'

/* Channel capability flags - used in alloc requests */
#define VDMA_CAP_SG           (1 << 0)
#define VDMA_CAP_CYCLIC       (1 << 1)
#define VDMA_CAP_INTERLEAVE   (1 << 2)
#define VDMA_CAP_MEMCPY       (1 << 3)
#define VDMA_CAP_MEMSET       (1 << 4)

/* Transfer direction */
#define VDMA_DIR_MEM_TO_DEV   0
#define VDMA_DIR_DEV_TO_MEM   1
#define VDMA_DIR_MEM_TO_MEM   2

/* Transfer operation flags */
#define VDMA_XFER_INTERRUPT   (1 << 0)
#define VDMA_XFER_FENCE       (1 << 1)
#define VDMA_XFER_CYCLIC      (1 << 2)

/* Channel status values */
#define VDMA_STAT_IDLE        0
#define VDMA_STAT_RUNNING     1
#define VDMA_STAT_PAUSED      2
#define VDMA_STAT_ERROR       3
#define VDMA_STAT_COMPLETED   4

/* Asynchronous event types */
#define VDMA_EVT_XFER_DONE   0
#define VDMA_EVT_ERROR        1
#define VDMA_EVT_THRESHOLD    2

/* Error codes reported in error events */
#define VDMA_ERR_BUS          1
#define VDMA_ERR_SLAVE        2
#define VDMA_ERR_DECODE       3
#define VDMA_ERR_TIMEOUT      4

/*
 * Channel handle - 32-bit unsigned.
 * Allocated by ALLOC, freed by FREE, referenced by all channel ops.
 */
typedef __u32 vdma_channel_t;

/*
 * Transfer cookie - 64-bit unsigned.
 * Returned by SUBMIT, used to query status or match events.
 */
typedef __u64 vdma_cookie_t;

/*
 * Fence value - 32-bit unsigned.
 * Used for cross-channel synchronization.
 */
typedef __u32 vdma_fence_t;

/*
 * Scatter-gather entry.
 * Wire format: addr (8 bytes), len (4 bytes), stride (4 bytes).
 */
struct vdma_sg_entry {
    __u64 addr;     /* bus/physical address */
    __u32 len;      /* segment length in bytes */
    __u32 stride;   /* stride for interleaved mode, 0 for contiguous */
};

/*
 * Channel allocation request.
 * The 'channel' field is written by the kernel on success (output).
 * The 'padding' field must be zero.
 */
struct vdma_alloc_req {
    __u32 caps;               /* input: required capabilities (VDMA_CAP_*) */
    __u32 priority;           /* input: 0-3 priority level */
    vdma_channel_t channel;   /* output: allocated channel handle */
    __u32 padding;            /* must be zero */
};

/*
 * Transfer descriptor - submit a DMA transfer.
 * The 'cookie' field is written by the kernel on success (output).
 * sg_list is a variable-length trailing array.
 */
struct vdma_xfer_desc {
    vdma_channel_t channel;   /* input: channel handle */
    __u32 direction;          /* input: VDMA_DIR_* */
    __u64 src_addr;           /* input: source address */
    __u64 dst_addr;           /* input: destination address */
    __u64 length;             /* input: transfer length in bytes */
    __u32 flags;              /* input: VDMA_XFER_* */
    __u32 sg_count;           /* input: number of SG entries (0 for simple) */
    vdma_cookie_t cookie;     /* output: transfer cookie */
    struct vdma_sg_entry sg_list[0]; /* variable-length SG list */
} __attribute__((packed));

/*
 * Transfer status query.
 * 'cookie' is input; all other fields are output.
 */
struct vdma_xfer_status {
    vdma_cookie_t cookie;     /* input: transfer cookie to query */
    __u32 status;             /* output: VDMA_STAT_* */
    __u32 bytes_remaining;    /* output: bytes left to transfer */
    __u64 timestamp;          /* output: completion timestamp in nanoseconds */
};

/*
 * Channel configuration.
 * max_sg_entries and max_burst_len are output (hardware limits).
 * The 'padding' field must be zero.
 */
struct vdma_chan_config {
    vdma_channel_t channel;   /* input: channel handle */
    __u32 burst_len;          /* input: burst length (power of 2, 1-256) */
    __u32 src_addr_width;     /* input: source address width in bytes (1,2,4,8) */
    __u32 dst_addr_width;     /* input: dest address width in bytes (1,2,4,8) */
    __u32 max_sg_entries;     /* output: max SG entries supported */
    __u32 max_burst_len;      /* output: max burst length supported */
    __u32 padding;            /* must be zero */
};

/*
 * Event sub-structures, discriminated by evt_type in vdma_event.
 */
struct vdma_event_xfer_done {
    vdma_cookie_t cookie;           /* completed transfer cookie */
    __u64 bytes_transferred;        /* total bytes transferred */
};

struct vdma_event_error {
    vdma_cookie_t cookie;           /* failed transfer cookie */
    __u32 error_code;               /* VDMA_ERR_* */
    __u32 error_addr_lo;            /* error address low 32 bits */
    __u32 error_addr_hi;            /* error address high 32 bits */
    __u32 padding;                  /* reserved */
};

struct vdma_event_threshold {
    __u32 watermark;                /* current watermark level */
    __u32 direction;                /* 0 = rising, 1 = falling */
};

/*
 * Asynchronous event notification.
 * The anonymous union is discriminated by evt_type:
 *   VDMA_EVT_XFER_DONE  -> xfer_done
 *   VDMA_EVT_ERROR       -> error
 *   VDMA_EVT_THRESHOLD   -> threshold
 */
struct vdma_event {
    vdma_channel_t channel;         /* channel that generated event */
    __u32 evt_type;                 /* VDMA_EVT_* */
    __u64 seq_num;                  /* monotonic event sequence number */
    union {
        struct vdma_event_xfer_done xfer_done;
        struct vdma_event_error error;
        struct vdma_event_threshold threshold;
    };
} __attribute__((packed));

/*
 * Fence synchronization request.
 * 'status' is output, all other fields are input.
 */
struct vdma_fence_req {
    vdma_channel_t channel;         /* input: channel handle */
    vdma_fence_t fence_val;         /* input: fence value to signal/wait */
    __u32 timeout_ms;               /* input: wait timeout (0 = poll only) */
    __u32 status;                   /* output: 0=signaled, 1=timeout, 2=error */
};

/*
 * Batch operation header.
 */
struct vdma_batch_hdr {
    __u32 num_xfers;                /* number of transfers in batch */
    __u32 flags;                    /* batch-level flags */
};

/*
 * Batch submission - submit multiple transfers atomically.
 * cookies is a variable-length output array, one cookie per transfer.
 */
struct vdma_batch_submit {
    struct vdma_batch_hdr header;
    vdma_cookie_t cookies[0];       /* output: array of cookies */
} __attribute__((packed));

/* ioctl commands */
#define VDMA_IOC_ALLOC      _IOWR(VDMA_MAGIC, 0x01, struct vdma_alloc_req)
#define VDMA_IOC_FREE       _IOW(VDMA_MAGIC, 0x02, vdma_channel_t)
#define VDMA_IOC_CONFIG     _IOWR(VDMA_MAGIC, 0x03, struct vdma_chan_config)
#define VDMA_IOC_SUBMIT     _IOWR(VDMA_MAGIC, 0x04, struct vdma_xfer_desc)
#define VDMA_IOC_STATUS     _IOWR(VDMA_MAGIC, 0x05, struct vdma_xfer_status)
#define VDMA_IOC_ABORT      _IOW(VDMA_MAGIC, 0x06, vdma_channel_t)
#define VDMA_IOC_PAUSE      _IOW(VDMA_MAGIC, 0x07, vdma_channel_t)
#define VDMA_IOC_RESUME     _IOW(VDMA_MAGIC, 0x08, vdma_channel_t)
#define VDMA_IOC_WAIT_EVT   _IOWR(VDMA_MAGIC, 0x09, struct vdma_event)
#define VDMA_IOC_FENCE      _IOWR(VDMA_MAGIC, 0x0A, struct vdma_fence_req)
#define VDMA_IOC_BATCH      _IOWR(VDMA_MAGIC, 0x0B, struct vdma_batch_submit)

#endif /* _UAPI_LINUX_VDMA_H */
