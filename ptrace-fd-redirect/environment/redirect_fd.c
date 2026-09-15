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

/*
 * redirect_fd: Redirect a running process's stdout/stderr to a new file
 * using ptrace-based syscall injection on x86_64 Linux.
 *
 * Usage: redirect_fd <pid> <output_file>
 *
 * Architecture: x86_64 only. Uses PTRACE_GETREGS/PTRACE_SETREGS with
 * struct user_regs_struct.
 *
 * x86_64 syscall ABI reference:
 *   Syscall number: orig_rax (read by kernel at syscall-entry)
 *   Arguments:      rdi, rsi, rdx, r10, r8, r9
 *   Return value:   rax (set by kernel at syscall-exit)
 *   The 'syscall' instruction is 2 bytes (0x0F 0x05).
 *   At both entry and exit stops, rip points to the instruction AFTER 'syscall'.
 *
 * ptrace syscall-stop protocol:
 *   With PTRACE_O_TRACESYSGOOD, syscall-stops have WSTOPSIG == (SIGTRAP | 0x80).
 *   Stops alternate: entry -> exit -> entry -> exit -> ...
 *   At entry: kernel has NOT yet executed the syscall (orig_rax determines which).
 *   At exit: kernel has completed the syscall (rax holds the return value).
 *
 * Chained injection technique:
 *   To inject multiple syscalls in sequence, after each injection's syscall-exit:
 *   1. Rewind rip by 2 (back to the 'syscall' instruction)
 *   2. PTRACE_SYSCALL to re-enter the 'syscall' instruction -> next entry stop
 *   3. At this new entry, inject the next syscall by setting orig_rax + args
 *   After all injections, restore original registers and PTRACE_DETACH.
 *   The process re-executes its original syscall and continues normally.
 */

#define SYSCALL_INSN_SIZE 2  /* bytes: x86_64 'syscall' = 0F 05 */
#define SCRATCH_SIZE 4096

struct proc_state {
    struct user_regs_struct regs;
};

/*
 * Wait for the tracee to stop at a syscall boundary.
 * Forwards any non-syscall signals back to the tracee.
 * Returns 0 on syscall-stop, -1 if the tracee exited/died.
 *
 * IMPORTANT: Requires PTRACE_O_TRACESYSGOOD to be set, otherwise
 * syscall-stops are indistinguishable from SIGTRAP signal-stops.
 */
static int wait_for_syscall_stop(pid_t child) {
    /* TODO: Implement
     *
     * Loop:
     *   waitpid(child, &status, 0)
     *   if WIFEXITED(status) || WIFSIGNALED(status): return -1
     *   if WIFSTOPPED(status):
     *     sig = WSTOPSIG(status)
     *     if sig == (SIGTRAP | 0x80): return 0  // syscall stop
     *     else: ptrace(PTRACE_SYSCALL, child, 0, sig)  // forward signal, continue
     */
    (void)child;
    return -1;
}

/*
 * Inject a single syscall into the tracee.
 *
 * PRECONDITION:  tracee is stopped at a syscall-ENTRY-stop.
 * POSTCONDITION: tracee is stopped at the NEXT syscall-ENTRY-stop,
 *                ready for another injection or for restore + detach.
 *
 * Steps:
 *   1. PTRACE_GETREGS; set orig_rax, rdi..r9; PTRACE_SETREGS
 *   2. PTRACE_SYSCALL -> wait -> now at syscall-EXIT
 *   3. PTRACE_GETREGS; rv = rax
 *   4. rip -= SYSCALL_INSN_SIZE; PTRACE_SETREGS
 *   5. PTRACE_SYSCALL -> wait -> now at syscall-ENTRY (re-entered)
 *   6. Return rv
 *
 * The rip rewind in step 4 causes the tracee to re-execute the same
 * 'syscall' instruction, producing a new entry stop. The kernel captures
 * whatever is in rax as orig_rax, but the next injection overwrites it.
 */
static long inject_syscall(pid_t child, long sysno,
                           long arg0, long arg1, long arg2,
                           long arg3, long arg4, long arg5) {
    /* TODO: Implement */
    (void)child; (void)sysno;
    (void)arg0; (void)arg1; (void)arg2;
    (void)arg3; (void)arg4; (void)arg5;
    return -1;
}

/*
 * Write a null-terminated string into the tracee's address space.
 *
 * Uses PTRACE_POKEDATA to write one word (8 bytes on x86_64) at a time.
 * For the final partial word: read the existing word with PTRACE_PEEKDATA,
 * overlay the remaining bytes (including null terminator), write back.
 *
 * Note: PTRACE_PEEKDATA returns a long and signals errors via errno
 * (the return value itself could be any bit pattern, including values
 * that look like -1). Always clear errno before calling PTRACE_PEEKDATA.
 */
static int write_string_to_child(pid_t child, unsigned long addr, const char *str) {
    /* TODO: Implement */
    (void)child; (void)addr; (void)str;
    return -1;
}

/*
 * Perform the full stdout/stderr redirect sequence.
 *
 * High-level flow:
 *   PTRACE_ATTACH -> wait for SIGSTOP
 *   PTRACE_SETOPTIONS(PTRACE_O_TRACESYSGOOD)
 *   PTRACE_SYSCALL -> wait for first syscall-entry
 *   Save registers
 *   inject mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0)
 *   write output_path into scratch page
 *   inject openat(AT_FDCWD, scratch, O_WRONLY|O_CREAT|O_TRUNC, 0644)
 *   inject dup2(new_fd, STDOUT_FILENO)
 *   inject dup2(new_fd, STDERR_FILENO)
 *   inject close(new_fd)
 *   inject munmap(scratch, 4096)
 *   Restore saved registers
 *   PTRACE_DETACH
 *
 * On error, clean up any allocated resources in the tracee before detaching.
 */
static int do_redirect(pid_t child, const char *output_path) {
    /* TODO: Implement */
    (void)child; (void)output_path;
    return -1;
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
        fprintf(stderr, "Failed to redirect PID %d: %s\n", target, strerror(result));
        return 1;
    }

    printf("Successfully redirected PID %d to %s\n", target, output_path);
    return 0;
}
