 *
 * redirect_fd_solution.c — Complete ptrace-based FD redirector.
 *
 * Attaches to a running process, injects syscalls to redirect its
 * stdout (fd 1) and stderr (fd 2) to a new file, then detaches
 * cleanly so the process continues with its original register state.
 *
 * x86_64 Linux only.
 */
#define _GNU_SOURCE
#include <sys/ptrace.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/user.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>

#define SYSCALL_INSN_SIZE 2  /* x86_64 'syscall' = 0F 05 */
#define SCRATCH_SIZE 4096

struct proc_state {
    struct user_regs_struct regs;
};

/*
 * Wait for a syscall-stop, forwarding any signal-stops back to the tracee.
 * Returns 0 on syscall-stop, -1 if the tracee exited.
 */
static int wait_for_syscall_stop(pid_t child) {
    int status;
    for (;;) {
        waitpid(child, &status, 0);
        if (WIFEXITED(status) || WIFSIGNALED(status))
            return -1;
        if (WIFSTOPPED(status)) {
            int sig = WSTOPSIG(status);
            if (sig == (SIGTRAP | 0x80))
                return 0;                    /* syscall-stop */
            /* Forward the signal and continue to next stop */
            ptrace(PTRACE_SYSCALL, child, 0, (void *)(long)sig);
            continue;
        }
        return -1;
    }
}

/*
 * Inject a single syscall.
 *
 * PRE:  child at syscall-ENTRY-stop.
 * POST: child at next syscall-ENTRY-stop (ready for chained injection).
 * Returns the injected syscall's return value.
 */
static long inject_syscall(pid_t child, long sysno,
                           long a0, long a1, long a2,
                           long a3, long a4, long a5) {
    struct user_regs_struct regs;

    /* 1. Set up the injected syscall */
    if (ptrace(PTRACE_GETREGS, child, 0, &regs) < 0) {
        perror("inject: GETREGS");
        return -1;
    }
    regs.orig_rax = sysno;
    regs.rdi = a0;
    regs.rsi = a1;
    regs.rdx = a2;
    regs.r10 = a3;
    regs.r8  = a4;
    regs.r9  = a5;
    if (ptrace(PTRACE_SETREGS, child, 0, &regs) < 0) {
        perror("inject: SETREGS");
        return -1;
    }

    /* 2. Execute to syscall-EXIT */
    if (ptrace(PTRACE_SYSCALL, child, 0, 0) < 0) {
        perror("inject: SYSCALL (to exit)");
        return -1;
    }
    if (wait_for_syscall_stop(child) < 0)
        return -1;

    /* 3. Read return value */
    if (ptrace(PTRACE_GETREGS, child, 0, &regs) < 0) {
        perror("inject: GETREGS (rv)");
        return -1;
    }
    long rv = (long)regs.rax;

    /* 4. Rewind rip to the 'syscall' instruction */
    regs.rip -= SYSCALL_INSN_SIZE;
    if (ptrace(PTRACE_SETREGS, child, 0, &regs) < 0) {
        perror("inject: SETREGS (rewind)");
        return -1;
    }

    /* 5. Advance to next syscall-ENTRY (re-enters the same instruction) */
    if (ptrace(PTRACE_SYSCALL, child, 0, 0) < 0) {
        perror("inject: SYSCALL (to entry)");
        return -1;
    }
    if (wait_for_syscall_stop(child) < 0)
        return -1;

    return rv;
}

/*
 * Write a null-terminated string into the child's address space,
 * word by word via PTRACE_POKEDATA.
 */
static int write_string_to_child(pid_t child, unsigned long addr,
                                 const char *str) {
    size_t len = strlen(str) + 1;          /* include NUL */
    const size_t ws = sizeof(unsigned long);

    /* Full words */
    while (len >= ws) {
        unsigned long word;
        memcpy(&word, str, ws);
        if (ptrace(PTRACE_POKEDATA, child, (void *)addr, (void *)word) < 0) {
            perror("poke");
            return -1;
        }
        addr += ws;
        str  += ws;
        len  -= ws;
    }

    /* Partial final word */
    if (len > 0) {
        errno = 0;
        unsigned long word = ptrace(PTRACE_PEEKDATA, child, (void *)addr, 0);
        if (errno) {
            perror("peek");
            return -1;
        }
        memcpy(&word, str, len);
        if (ptrace(PTRACE_POKEDATA, child, (void *)addr, (void *)word) < 0) {
            perror("poke partial");
            return -1;
        }
    }

    return 0;
}

/*
 * Full redirect sequence.  Returns 0 on success, errno-style on failure.
 */
static int do_redirect(pid_t child, const char *output_path) {
    struct proc_state saved;
    int status;
    int err = 0;

    /* ---- attach -------------------------------------------------- */
    if (ptrace(PTRACE_ATTACH, child, 0, 0) < 0) {
        perror("PTRACE_ATTACH");
        return errno;
    }
    waitpid(child, &status, 0);
    if (!WIFSTOPPED(status)) {
        ptrace(PTRACE_DETACH, child, 0, 0);
        return ECHILD;
    }

    /* ---- set options --------------------------------------------- */
    if (ptrace(PTRACE_SETOPTIONS, child, 0,
               (void *)(long)PTRACE_O_TRACESYSGOOD) < 0) {
        err = errno;
        ptrace(PTRACE_DETACH, child, 0, 0);
        return err;
    }

    /* ---- advance to first syscall-entry -------------------------- */
    if (ptrace(PTRACE_SYSCALL, child, 0, 0) < 0) {
        err = errno;
        ptrace(PTRACE_DETACH, child, 0, 0);
        return err;
    }
    if (wait_for_syscall_stop(child) < 0) {
        return ECHILD;
    }

    /* ---- save registers ------------------------------------------ */
    if (ptrace(PTRACE_GETREGS, child, 0, &saved.regs) < 0) {
        err = errno;
        ptrace(PTRACE_DETACH, child, 0, 0);
        return err;
    }

    /* ---- inject mmap for scratch page ---------------------------- */
    long scratch = inject_syscall(child, SYS_mmap,
                                  0, SCRATCH_SIZE,
                                  PROT_READ | PROT_WRITE,
                                  MAP_PRIVATE | MAP_ANONYMOUS,
                                  -1, 0);
    if ((unsigned long)scratch >= (unsigned long)-4096UL) {
        fprintf(stderr, "mmap injection failed: %ld\n", scratch);
        err = ENOMEM;
        goto restore;
    }

    /* ---- write output path into scratch page --------------------- */
    if (write_string_to_child(child, (unsigned long)scratch,
                              output_path) < 0) {
        err = EIO;
        goto cleanup_mmap;
    }

    /* ---- inject openat ------------------------------------------- */
    long new_fd = inject_syscall(child, SYS_openat,
                                 (long)AT_FDCWD, scratch,
                                 O_WRONLY | O_CREAT | O_TRUNC,
                                 0644, 0, 0);
    if (new_fd < 0) {
        fprintf(stderr, "openat failed: %ld\n", new_fd);
        err = ENOENT;
        goto cleanup_mmap;
    }

    /* ---- inject dup2 for stdout ---------------------------------- */
    long ret = inject_syscall(child, SYS_dup2,
                              new_fd, STDOUT_FILENO, 0, 0, 0, 0);
    if (ret < 0) {
        fprintf(stderr, "dup2(stdout) failed: %ld\n", ret);
        err = EIO;
        goto cleanup_fd;
    }

    /* ---- inject dup2 for stderr ---------------------------------- */
    ret = inject_syscall(child, SYS_dup2,
                         new_fd, STDERR_FILENO, 0, 0, 0, 0);
    if (ret < 0) {
        fprintf(stderr, "dup2(stderr) failed: %ld\n", ret);
        err = EIO;
        goto cleanup_fd;
    }

    /* ---- inject close(new_fd) ------------------------------------ */
    inject_syscall(child, SYS_close, new_fd, 0, 0, 0, 0, 0);

    /* ---- inject munmap(scratch) ---------------------------------- */
    inject_syscall(child, SYS_munmap, scratch, SCRATCH_SIZE, 0, 0, 0, 0);

    /* ---- restore and detach -------------------------------------- */
    ptrace(PTRACE_SETREGS, child, 0, &saved.regs);
    ptrace(PTRACE_DETACH, child, 0, 0);
    return 0;

cleanup_fd:
    inject_syscall(child, SYS_close, new_fd, 0, 0, 0, 0, 0);
cleanup_mmap:
    inject_syscall(child, SYS_munmap, scratch, SCRATCH_SIZE, 0, 0, 0, 0);
restore:
    ptrace(PTRACE_SETREGS, child, 0, &saved.regs);
    ptrace(PTRACE_DETACH, child, 0, 0);
    return err;
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <pid> <output_file>\n", argv[0]);
        return 1;
    }

    pid_t target = atoi(argv[1]);
    const char *output_path = argv[2];

    if (target <= 0) {
        fprintf(stderr, "Invalid PID: %s\n", argv[1]);
        return 1;
    }

    int result = do_redirect(target, output_path);
    if (result != 0) {
        fprintf(stderr, "Failed to redirect PID %d: %s\n",
                target, strerror(result));
        return 1;
    }

    printf("Successfully redirected PID %d to %s\n", target, output_path);
    return 0;
}
