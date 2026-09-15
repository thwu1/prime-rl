/*
 * SECCOMP BPF Binary Filter Loader and Tester
 *
 * Loads a binary BPF filter file (sock_filter wire format) into the kernel's
 * SECCOMP subsystem, forks a child that attempts the specified syscall, and
 * reports whether the syscall was ALLOWED or KILLED by the filter.
 *
 * Usage: ./seccomp_loader <bpf_file> <syscall_nr> [arg0] [arg1] [arg2]
 *
 * The binary format is: each instruction is 8 bytes
 *   - 2-byte little-endian code (u16)
 *   - 1-byte jt (u8)
 *   - 1-byte jf (u8)
 *   - 4-byte little-endian k (u32)
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <sys/syscall.h>
#include <linux/seccomp.h>
#include <linux/filter.h>

static struct sock_filter *load_bpf(const char *path, unsigned short *count)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        perror("fopen");
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (size <= 0 || size % (long)sizeof(struct sock_filter) != 0) {
        fprintf(stderr, "Invalid BPF file: size %ld not a positive multiple of %zu\n",
                size, sizeof(struct sock_filter));
        fclose(f);
        return NULL;
    }

    *count = (unsigned short)(size / sizeof(struct sock_filter));
    struct sock_filter *prog = malloc(size);
    if (!prog) {
        perror("malloc");
        fclose(f);
        return NULL;
    }
    if (fread(prog, 1, size, f) != (size_t)size) {
        perror("fread");
        free(prog);
        fclose(f);
        return NULL;
    }
    fclose(f);
    return prog;
}

static void dump_filter(const struct sock_filter *prog, unsigned short count)
{
    printf("Filter: %d instructions\n", count);
    for (int i = 0; i < count; i++) {
        printf("  [%2d] code=0x%04x jt=%d jf=%d k=0x%08x (%u)\n",
               i, prog[i].code, prog[i].jt, prog[i].jf, prog[i].k, prog[i].k);
    }
}

int main(int argc, char *argv[])
{
    if (argc < 3) {
        fprintf(stderr,
            "Usage: %s <bpf_file> <syscall_nr> [arg0] [arg1] [arg2]\n"
            "       %s --dump <bpf_file>\n"
            "\n"
            "Loads a binary BPF filter and tests it against the specified syscall.\n"
            "Reports ALLOWED or KILLED based on the kernel SECCOMP decision.\n"
            "Use --dump to disassemble the binary filter without executing.\n",
            argv[0], argv[0]);
        return 1;
    }

    /* Handle --dump mode */
    if (strcmp(argv[1], "--dump") == 0) {
        if (argc < 3) {
            fprintf(stderr, "Usage: %s --dump <bpf_file>\n", argv[0]);
            return 1;
        }
        unsigned short count;
        struct sock_filter *prog = load_bpf(argv[2], &count);
        if (!prog) return 1;
        dump_filter(prog, count);
        free(prog);
        return 0;
    }

    const char *bpf_path = argv[1];
    int nr = atoi(argv[2]);
    long a0 = argc > 3 ? strtol(argv[3], NULL, 0) : 0;
    long a1 = argc > 4 ? strtol(argv[4], NULL, 0) : 0;
    long a2 = argc > 5 ? strtol(argv[5], NULL, 0) : 0;

    unsigned short count;
    struct sock_filter *filter = load_bpf(bpf_path, &count);
    if (!filter) return 1;

    printf("filter=%s syscall=%d args=[%ld,%ld,%ld] result=",
           bpf_path, nr, a0, a1, a2);
    fflush(stdout);

    pid_t pid = fork();
    if (pid < 0) {
        perror("fork");
        free(filter);
        return 1;
    }

    if (pid == 0) {
        /* Child: install SECCOMP filter and attempt syscall */
        if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) {
            perror("NO_NEW_PRIVS");
            _exit(2);
        }

        struct sock_fprog prog = { .len = count, .filter = filter };
        if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &prog)) {
            perror("SECCOMP_FILTER");
            _exit(2);
        }

        /* Attempt the syscall */
        long ret = syscall(nr, a0, a1, a2, 0, 0, 0);
        printf("ALLOWED (ret=%ld errno=%d)\n", ret, errno);
        fflush(stdout);
        _exit(0);
    }

    /* Parent: wait and interpret exit status */
    int status;
    waitpid(pid, &status, 0);

    if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        if (sig == SIGSYS) {
            printf("KILLED\n");
        } else {
            printf("SIGNAL(%d)\n", sig);
        }
    } else if (WIFEXITED(status)) {
        int code = WEXITSTATUS(status);
        if (code == 2) {
            printf("SECCOMP_SETUP_FAILED\n");
        }
        /* code 0 means child already printed ALLOWED */
    } else {
        printf("UNKNOWN(status=0x%x)\n", status);
    }

    free(filter);
    return 0;
}
