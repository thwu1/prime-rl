/*
 * pledge_impl.c - Complete SECCOMP BPF pledge() implementation
 *
 * Builds a linear BPF filter program that:
 *   1. Validates architecture (AUDIT_ARCH_X86_64)
 *   2. Always allows exit/exit_group
 *   3. Emits JEQ+RET_ALLOW pairs for each promise category's syscalls
 *   4. Uses 7-instruction argument-filtering blocks for:
 *      - openat flags (rpath: O_ACCMODE == O_RDONLY)
 *      - socket domain (inet: AF_INET or AF_INET6)
 *   5. Default action: SECCOMP_RET_KILL_PROCESS
 *
 */
#define _GNU_SOURCE
#include "pledge.h"
#include <stddef.h>
#include <string.h>
#include <stdint.h>
#include <linux/seccomp.h>
#include <linux/filter.h>
#include <linux/audit.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <errno.h>

/* Promise category bit flags */
#define PF_STDIO  (1u << 0)
#define PF_RPATH  (1u << 1)
#define PF_WPATH  (1u << 2)
#define PF_CPATH  (1u << 3)
#define PF_INET   (1u << 4)
#define PF_PROC   (1u << 5)

/* seccomp_data field offsets (x86_64, stable ABI) */
#define OFF_NR   0   /* offsetof(struct seccomp_data, nr)      */
#define OFF_ARCH 4   /* offsetof(struct seccomp_data, arch)    */
#define OFF_ARG0 16  /* offsetof(struct seccomp_data, args[0]) */
#define OFF_ARG2 32  /* offsetof(struct seccomp_data, args[2]) */

#define MAX_FILTER 512

/* Compound-literal BPF instruction helpers (usable in assignments) */
#define BPFS(code, k) \
    ((struct sock_filter){ \
        (unsigned short)(code), 0, 0, (unsigned int)(k)})
#define BPFJ(code, k, jt, jf) \
    ((struct sock_filter){ \
        (unsigned short)(code), (unsigned char)(jt), \
        (unsigned char)(jf), (unsigned int)(k)})

/* Fallback definitions for syscall numbers that may not be in older headers */
#ifndef SYS_rseq
#define SYS_rseq 334
#endif
#ifndef SYS_clone3
#define SYS_clone3 435
#endif
#ifndef SYS_faccessat2
#define SYS_faccessat2 439
#endif
#ifndef SYS_renameat2
#define SYS_renameat2 316
#endif

/* ------------------------------------------------------------------ */

static unsigned int parse_promises(const char *promises)
{
    unsigned int flags = 0;
    const char *p = promises;

    while (*p) {
        while (*p == ' ') p++;
        if (!*p) break;

        const char *s = p;
        while (*p && *p != ' ') p++;
        size_t len = (size_t)(p - s);

        if      (len == 5 && !memcmp(s, "stdio", 5)) flags |= PF_STDIO;
        else if (len == 5 && !memcmp(s, "rpath", 5)) flags |= PF_RPATH;
        else if (len == 5 && !memcmp(s, "wpath", 5)) flags |= PF_WPATH;
        else if (len == 5 && !memcmp(s, "cpath", 5)) flags |= PF_CPATH;
        else if (len == 4 && !memcmp(s, "inet",  4)) flags |= PF_INET;
        else if (len == 4 && !memcmp(s, "proc",  4)) flags |= PF_PROC;
        else { errno = EINVAL; return (unsigned int)-1; }
    }
    return flags;
}

/* Emit: if (nr == syscall_nr) return ALLOW; */
static int emit_simple(struct sock_filter *f, int n, int nr)
{
    f[n++] = BPFJ(BPF_JMP | BPF_JEQ | BPF_K, nr, 0, 1);
    f[n++] = BPFS(BPF_RET | BPF_K, SECCOMP_RET_ALLOW);
    return n;
}

static int emit_list(struct sock_filter *f, int n,
                     const int *nrs, int count)
{
    for (int i = 0; i < count; i++)
        n = emit_simple(f, n, nrs[i]);
    return n;
}

/*
 * Emit 7-instruction argument-filtered block for openat (rpath).
 * Only allows openat when (flags & O_ACCMODE) == O_RDONLY.
 *
 * Layout (relative indices within block):
 *   [0] JEQ SYS_openat  → [1] (jt=0)  | skip block (jf=6)
 *   [1] LD  args[2]       (load flags)
 *   [2] AND O_ACCMODE(3)  (mask)
 *   [3] JEQ 0 (O_RDONLY) → [6] ALLOW (jt=2) | [4] (jf=0)
 *   [4] LD  nr            (reload syscall number)
 *   [5] JA  1             (skip ALLOW → [7])
 *   [6] RET ALLOW
 */
static int emit_openat_rdonly(struct sock_filter *f, int n)
{
    f[n++] = BPFJ(BPF_JMP | BPF_JEQ | BPF_K, SYS_openat, 0, 6);
    f[n++] = BPFS(BPF_LD  | BPF_W   | BPF_ABS, OFF_ARG2);
    f[n++] = BPFS(BPF_ALU | BPF_AND | BPF_K, 3); /* O_ACCMODE */
    f[n++] = BPFJ(BPF_JMP | BPF_JEQ | BPF_K, 0, 2, 0); /* O_RDONLY */
    f[n++] = BPFS(BPF_LD  | BPF_W   | BPF_ABS, OFF_NR);
    f[n++] = BPFS(BPF_JMP | BPF_JA, 1);
    f[n++] = BPFS(BPF_RET | BPF_K, SECCOMP_RET_ALLOW);
    return n;
}

/*
 * Emit 7-instruction argument-filtered block for socket (inet).
 * Only allows socket when domain == AF_INET (2) or AF_INET6 (10).
 *
 *   [0] JEQ SYS_socket   → [1] (jt=0)  | skip block (jf=6)
 *   [1] LD  args[0]        (load domain)
 *   [2] JEQ AF_INET(2)   → [6] ALLOW (jt=3) | [3] (jf=0)
 *   [3] JEQ AF_INET6(10) → [6] ALLOW (jt=2) | [4] (jf=0)
 *   [4] LD  nr             (reload)
 *   [5] JA  1              (skip ALLOW → [7])
 *   [6] RET ALLOW
 */
static int emit_socket_inet(struct sock_filter *f, int n)
{
    f[n++] = BPFJ(BPF_JMP | BPF_JEQ | BPF_K, SYS_socket, 0, 6);
    f[n++] = BPFS(BPF_LD  | BPF_W   | BPF_ABS, OFF_ARG0);
    f[n++] = BPFJ(BPF_JMP | BPF_JEQ | BPF_K, 2,  3, 0); /* AF_INET  */
    f[n++] = BPFJ(BPF_JMP | BPF_JEQ | BPF_K, 10, 2, 0); /* AF_INET6 */
    f[n++] = BPFS(BPF_LD  | BPF_W   | BPF_ABS, OFF_NR);
    f[n++] = BPFS(BPF_JMP | BPF_JA, 1);
    f[n++] = BPFS(BPF_RET | BPF_K, SECCOMP_RET_ALLOW);
    return n;
}

/* ------------------------------------------------------------------ */

int pledge(const char *promises, const char *execpromises)
{
    (void)execpromises;

    /* NULL promises = no restriction */
    if (!promises)
        return 0;

    unsigned int flags = parse_promises(promises);
    if (flags == (unsigned int)-1)
        return -1;

    struct sock_filter f[MAX_FILTER];
    int n = 0;

    /* ---- Section 1: Validate architecture ---- */
    f[n++] = BPFS(BPF_LD  | BPF_W   | BPF_ABS, OFF_ARCH);
    f[n++] = BPFJ(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0);
    f[n++] = BPFS(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS);

    /* ---- Section 2: Load syscall number ---- */
    f[n++] = BPFS(BPF_LD | BPF_W | BPF_ABS, OFF_NR);

    /* ---- Section 3: Always allow exit / exit_group ---- */
    n = emit_simple(f, n, SYS_exit_group);
    n = emit_simple(f, n, SYS_exit);

    /* ---- Section 4: stdio ---- */
    if (flags & PF_STDIO) {
        static const int sc[] = {
            SYS_read, SYS_write, SYS_close, SYS_fstat,
            SYS_lseek, SYS_mmap, SYS_mprotect, SYS_munmap,
            SYS_brk, SYS_rt_sigaction, SYS_rt_sigprocmask,
            SYS_rt_sigreturn, SYS_ioctl, SYS_pread64, SYS_pwrite64,
            SYS_writev, SYS_dup, SYS_dup2, SYS_nanosleep,
            SYS_getpid, SYS_poll, SYS_futex,
            SYS_set_tid_address, SYS_clock_gettime,
            SYS_set_robust_list, SYS_newfstatat,
            SYS_prlimit64, SYS_getrandom,
            SYS_arch_prctl, SYS_sched_yield,
            SYS_clock_nanosleep, SYS_rseq,
        };
        n = emit_list(f, n, sc, sizeof(sc) / sizeof(sc[0]));
    }

    /* ---- Section 5: rpath ---- */
    if (flags & PF_RPATH) {
        static const int sc[] = {
            SYS_access, SYS_getcwd, SYS_readlink,
            SYS_getdents64, SYS_readlinkat, SYS_faccessat,
            SYS_statfs, SYS_newfstatat, SYS_faccessat2,
        };
        n = emit_list(f, n, sc, sizeof(sc) / sizeof(sc[0]));

        /* openat with read-only argument check (skip if wpath also set) */
        if (!(flags & PF_WPATH))
            n = emit_openat_rdonly(f, n);
    }

    /* ---- Section 6: wpath ---- */
    if (flags & PF_WPATH) {
        static const int sc[] = {
            SYS_openat, SYS_ftruncate, SYS_fsync,
            SYS_fdatasync, SYS_fallocate,
        };
        n = emit_list(f, n, sc, sizeof(sc) / sizeof(sc[0]));
    }

    /* ---- Section 7: cpath ---- */
    if (flags & PF_CPATH) {
        static const int sc[] = {
            SYS_mkdir, SYS_rmdir, SYS_link, SYS_unlink,
            SYS_symlink, SYS_rename, SYS_mkdirat,
            SYS_unlinkat, SYS_linkat, SYS_symlinkat,
            SYS_renameat2,
        };
        n = emit_list(f, n, sc, sizeof(sc) / sizeof(sc[0]));
    }

    /* ---- Section 8: inet + socket domain check ---- */
    if (flags & PF_INET) {
        static const int sc[] = {
            SYS_connect, SYS_accept, SYS_sendto, SYS_recvfrom,
            SYS_sendmsg, SYS_recvmsg, SYS_bind, SYS_listen,
            SYS_getsockname, SYS_getpeername,
            SYS_setsockopt, SYS_getsockopt,
            SYS_accept4, SYS_shutdown,
        };
        n = emit_list(f, n, sc, sizeof(sc) / sizeof(sc[0]));
        n = emit_socket_inet(f, n);
    }

    /* ---- Section 9: proc ---- */
    if (flags & PF_PROC) {
        static const int sc[] = {
            SYS_clone, SYS_fork, SYS_vfork, SYS_execve,
            SYS_wait4, SYS_kill, SYS_waitid, SYS_clone3,
        };
        n = emit_list(f, n, sc, sizeof(sc) / sizeof(sc[0]));
    }

    /* ---- Section 10: Default deny ---- */
    f[n++] = BPFS(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS);

    /* ---- Install filter ---- */
    struct sock_fprog prog = {
        .len = (unsigned short)n,
        .filter = f,
    };

    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0)
        return -1;
    if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &prog) != 0)
        return -1;

    return 0;
}
