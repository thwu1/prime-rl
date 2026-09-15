/*
 * pledge.h - OpenBSD-style pledge(2) for Linux using SECCOMP BPF
 *
 */
#ifndef PLEDGE_H
#define PLEDGE_H

/**
 * Restrict system calls available to the calling process.
 *
 * @param promises  Space-separated list of promise categories:
 *                  "stdio"  - basic I/O (read, write, close, mmap, brk, etc.)
 *                  "rpath"  - read-only filesystem (stat, openat O_RDONLY)
 *                  "wpath"  - writable filesystem (openat any flags, ftruncate)
 *                  "cpath"  - create/delete paths (mkdir, unlink, rename, etc.)
 *                  "inet"   - internet sockets (AF_INET/AF_INET6 only)
 *                  "proc"   - process control (clone, wait4, execve, kill)
 *                  NULL means no restriction; "" means only exit allowed.
 * @param execpromises  Reserved (ignored), pass NULL.
 * @return 0 on success, -1 on error with errno set.
 */
int pledge(const char *promises, const char *execpromises);

#endif /* PLEDGE_H */
