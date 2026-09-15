/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
/*
 * Hardware Accelerator Device Driver UAPI
 *
 * Userspace interface for the hwaccel device driver.
 * Provides context management, buffer allocation, job submission,
 * event notification, and debug/diagnostic interfaces.
 */
#ifndef _LINUX_HWACCEL_H
#define _LINUX_HWACCEL_H

#include <linux/types.h>
#include <linux/ioctl.h>

#define HWACCEL_IOC_MAGIC       'H'

/* --- Data structures --------------------------------------------------- */

struct hwaccel_ctx_info {
    __u32 ctx_id;
    __u32 capabilities;
    __u32 reserved[2];
};

struct hwaccel_buf_alloc {
    __u64 size;
    __u32 flags;
    __u32 alignment;
    __s32 handle;
    __u32 __reserved;
    __u64 gpu_addr;
};

struct hwaccel_buf_free {
    __s32 handle;
    __u32 __reserved;
};

struct hwaccel_buf_map {
    __s32 handle;
    __u32 __reserved;
    __u64 offset;
    __u64 length;
    __u64 cpu_addr;
};

struct hwaccel_queue_info {
    __u32 queue_id;
    __u32 max_jobs;
};

struct hwaccel_job_submit {
    __u32 queue_prio;
    __u32 job_type;
    __u32 flags;
    __u32 num_bufs;
    __u64 buf_handles;
    __u64 cmd_buf;
    __u32 cmd_size;
    __u32 __reserved;
    __u64 fence_val;
};

struct hwaccel_job_wait {
    __u64 timeout_ns;
    __u32 flags;
    __s32 job_status;
};

struct hwaccel_event_info {
    __u32 event_id;
    __u32 event_mask;
};

struct hwaccel_cancel_req {
    __s64 job_id;
    __u32 force;
    __u32 __reserved;
};

struct hwaccel_dev_info {
    __u32 num_cores;
    __u32 max_freq_mhz;
    __u64 memory_size;
    __u8  driver_version[64];
    __u8  fw_version[32];
};

struct hwaccel_power_config {
    __u32 mode;
    __u32 timeout_ms;
};

/* Debug/diagnostic structures */
struct hwaccel_reg_access {
    __u32 offset;
    __u32 value;
};

struct hwaccel_state_dump {
    __u32 num_entries;
    __u32 dump_flags;
    __u64 timestamp;
    __u8  data[48];
};

struct hwaccel_err_inject {
    __u32 error_type;
    __u32 target_core;
};

/* --- ioctl commands ---------------------------------------------------- */

/* Context lifecycle */
#define HWACCEL_CREATE_CTX      _IOWR(HWACCEL_IOC_MAGIC, 0x01, struct hwaccel_ctx_info)
#define HWACCEL_DESTROY_CTX     _IO(HWACCEL_IOC_MAGIC, 0x02)

/* Buffer management */
#define HWACCEL_ALLOC_BUF       _IOWR(HWACCEL_IOC_MAGIC, 0x03, struct hwaccel_buf_alloc)
#define HWACCEL_FREE_BUF        _IOW(HWACCEL_IOC_MAGIC, 0x04, struct hwaccel_buf_free)
#define HWACCEL_MAP_BUF         _IOWR(HWACCEL_IOC_MAGIC, 0x05, struct hwaccel_buf_map)

/* Queue management */
#define HWACCEL_CREATE_QUEUE    _IOWR(HWACCEL_IOC_MAGIC, 0x06, struct hwaccel_queue_info)
#define HWACCEL_SUBMIT_JOB      _IOW(HWACCEL_IOC_MAGIC, 0x07, struct hwaccel_job_submit)
#define HWACCEL_WAIT_JOB        _IOWR(HWACCEL_IOC_MAGIC, 0x08, struct hwaccel_job_wait)

/* Event notification */
#define HWACCEL_CREATE_EVENT    _IOWR(HWACCEL_IOC_MAGIC, 0x09, struct hwaccel_event_info)

/* Job control */
#define HWACCEL_CANCEL_JOB      _IOW(HWACCEL_IOC_MAGIC, 0x0a, struct hwaccel_cancel_req)

/* Device queries */
#define HWACCEL_GET_INFO        _IOR(HWACCEL_IOC_MAGIC, 0x0b, struct hwaccel_dev_info)

/* Power management */
#define HWACCEL_SET_POWER       _IOW(HWACCEL_IOC_MAGIC, 0x0c, struct hwaccel_power_config)

/* Debug/diagnostic */
#define HWACCEL_DBG_READ_REG    _IOWR(HWACCEL_IOC_MAGIC, 0x10, struct hwaccel_reg_access)
#define HWACCEL_DBG_WRITE_REG   _IOW(HWACCEL_IOC_MAGIC, 0x11, struct hwaccel_reg_access)
#define HWACCEL_DBG_DUMP_STATE  _IOR(HWACCEL_IOC_MAGIC, 0x12, struct hwaccel_state_dump)
#define HWACCEL_DBG_INJECT_ERR  _IOW(HWACCEL_IOC_MAGIC, 0x13, struct hwaccel_err_inject)

/* --- Flag/enum values -------------------------------------------------- */

/* Buffer allocation flags */
#define HWACCEL_BUF_CACHED      0x1
#define HWACCEL_BUF_CONTIGUOUS  0x2
#define HWACCEL_BUF_SECURE      0x4

/* Job flags */
#define HWACCEL_JOB_HIGH_PRIO   0x1
#define HWACCEL_JOB_PREEMPTIBLE 0x2

/* Job types */
#define HWACCEL_JOB_COMPUTE     0x0
#define HWACCEL_JOB_COPY        0x1
#define HWACCEL_JOB_FILL        0x2

/* Event types */
#define HWACCEL_EVENT_JOB_DONE  0x1
#define HWACCEL_EVENT_CTX_ERROR 0x2
#define HWACCEL_EVENT_THERMAL   0x4

/* Power modes */
#define HWACCEL_PM_FULL         0x0
#define HWACCEL_PM_LOW          0x1
#define HWACCEL_PM_IDLE         0x2

/* Debug levels */
#define HWACCEL_DBG_NONE        0x0
#define HWACCEL_DBG_ERROR       0x1
#define HWACCEL_DBG_WARN        0x2
#define HWACCEL_DBG_INFO        0x3
#define HWACCEL_DBG_VERBOSE     0x4

/* Error injection types */
#define HWACCEL_ERR_PARITY      0x1
#define HWACCEL_ERR_TIMEOUT     0x2
#define HWACCEL_ERR_BUS         0x3

#endif /* _LINUX_HWACCEL_H */
