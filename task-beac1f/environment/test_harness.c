/*
 * test_harness.c - Verification suite for SECCOMP BPF pledge()
 *
 * Each test forks a child, installs pledge(), attempts an operation,
 * and the parent checks whether the child succeeded or was killed
 * by SIGSYS (signal 31) from SECCOMP_RET_KILL_PROCESS.
 *
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/wait.h>
#include <sys/syscall.h>
#include <sys/resource.h>
#include <signal.h>
#include <errno.h>
#include "pledge.h"

#ifndef SIGSYS
#define SIGSYS 31
#endif

static int g_passed = 0;
static int g_failed = 0;

static void run_test(const char *name, const char *promises,
                     void (*child_fn)(void), int expect_killed)
{
    fflush(stdout);
    fflush(stderr);

    pid_t pid = fork();
    if (pid < 0) {
        printf("FAIL %s: fork failed: %s\n", name, strerror(errno));
        g_failed++;
        return;
    }

    if (pid == 0) {
        /* Child: install pledge, then run test action */
        if (pledge(promises, NULL) != 0) {
            const char msg[] = "pledge() failed\n";
            syscall(SYS_write, 2, msg, sizeof(msg) - 1);
            syscall(SYS_exit_group, 99);
        }
        child_fn();
        syscall(SYS_exit_group, 0);
    }

    /* Parent: wait and evaluate */
    int status = 0;
    waitpid(pid, &status, 0);

    if (expect_killed) {
        if (WIFSIGNALED(status) && WTERMSIG(status) == SIGSYS) {
            printf("PASS %s\n", name);
            g_passed++;
        } else if (WIFEXITED(status) && WEXITSTATUS(status) == 99) {
            printf("FAIL %s: pledge() returned error\n", name);
            g_failed++;
        } else if (WIFEXITED(status)) {
            printf("FAIL %s: expected SIGSYS kill but child exited %d\n",
                   name, WEXITSTATUS(status));
            g_failed++;
        } else if (WIFSIGNALED(status)) {
            printf("FAIL %s: expected SIGSYS(%d) but got signal %d\n",
                   name, SIGSYS, WTERMSIG(status));
            g_failed++;
        } else {
            printf("FAIL %s: unexpected wait status 0x%x\n", name, status);
            g_failed++;
        }
    } else {
        if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
            printf("PASS %s\n", name);
            g_passed++;
        } else if (WIFEXITED(status) && WEXITSTATUS(status) == 99) {
            printf("FAIL %s: pledge() returned error\n", name);
            g_failed++;
        } else if (WIFSIGNALED(status)) {
            printf("FAIL %s: expected success but killed by signal %d\n",
                   name, WTERMSIG(status));
            g_failed++;
        } else if (WIFEXITED(status)) {
            printf("FAIL %s: expected exit(0) but got exit(%d)\n",
                   name, WEXITSTATUS(status));
            g_failed++;
        } else {
            printf("FAIL %s: unexpected wait status 0x%x\n", name, status);
            g_failed++;
        }
    }
}

/* ---- Child test functions (run after pledge is installed) ----
 *
 * These use raw syscall() to avoid glibc-internal syscalls that
 * could interfere with the seccomp filter under test.
 */

static void child_write_stdout(void)
{
    syscall(SYS_write, 1, "ok\n", 3);
}

static void child_openat_attempt(void)
{
    /* Attempt openat — should be killed if not in allowed set */
    syscall(SYS_openat, AT_FDCWD, "/etc/hostname", O_RDONLY, 0);
}

static void child_openat_rdonly(void)
{
    long fd = syscall(SYS_openat, AT_FDCWD, "/etc/hostname", O_RDONLY, 0);
    if (fd < 0)
        syscall(SYS_exit_group, 1);
    syscall(SYS_close, (int)fd);
}

static void child_openat_wronly(void)
{
    /* O_WRONLY: O_ACCMODE & flags != 0, should be blocked by rpath */
    syscall(SYS_openat, AT_FDCWD, "/tmp/pledge_test_file", O_WRONLY, 0);
}

static void child_openat_wronly_ok(void)
{
    long fd = syscall(SYS_openat, AT_FDCWD, "/tmp/pledge_test_file",
                      O_WRONLY, 0);
    if (fd < 0)
        syscall(SYS_exit_group, 1);
    syscall(SYS_close, (int)fd);
}

static void child_socket_inet(void)
{
    long fd = syscall(SYS_socket, 2 /*AF_INET*/, 1 /*SOCK_STREAM*/, 0);
    if (fd < 0)
        syscall(SYS_exit_group, 1);
    syscall(SYS_close, (int)fd);
}

static void child_socket_unix(void)
{
    /* AF_UNIX=1 — should be blocked by inet's domain filter */
    syscall(SYS_socket, 1 /*AF_UNIX*/, 1 /*SOCK_STREAM*/, 0);
}

static void child_socket_any(void)
{
    /* Any socket call — should be killed under stdio-only pledge */
    syscall(SYS_socket, 2 /*AF_INET*/, 1 /*SOCK_STREAM*/, 0);
}

static void child_clone_fork(void)
{
    long pid = syscall(SYS_clone, (long)SIGCHLD, (long)0, (long)0, (long)0, (long)0);
    if (pid == 0) {
        syscall(SYS_exit_group, 0);
    } else if (pid > 0) {
        syscall(SYS_wait4, (int)pid, (long)0, 0, (long)0);
    } else {
        syscall(SYS_exit_group, 1);
    }
}

static void child_clone_attempt(void)
{
    syscall(SYS_clone, (long)SIGCHLD, (long)0, (long)0, (long)0, (long)0);
}

static void child_write_blocked(void)
{
    /* Under empty pledge, even write should be killed */
    syscall(SYS_write, 1, "should not appear\n", 18);
}

static void child_exit_only(void)
{
    /* Empty body: returns to caller which invokes exit_group (always allowed) */
}

int main(void)
{
    /* Suppress core dumps from SIGSYS kills */
    struct rlimit rl = {0, 0};
    setrlimit(RLIMIT_CORE, &rl);

    /* Overall timeout */
    alarm(120);

    /* Create test file for wpath tests */
    int tfd = open("/tmp/pledge_test_file",
                   O_CREAT | O_WRONLY | O_TRUNC, 0644);
    if (tfd >= 0) close(tfd);

    printf("=== Pledge SECCOMP BPF Test Suite ===\n");

    /* T1: stdio allows SYS_write */
    run_test("stdio_write_allowed", "stdio",
             child_write_stdout, 0);

    /* T2: stdio blocks SYS_openat */
    run_test("stdio_openat_blocked", "stdio",
             child_openat_attempt, 1);

    /* T3: rpath allows openat(O_RDONLY) via argument filter */
    run_test("rpath_openat_rdonly", "stdio rpath",
             child_openat_rdonly, 0);

    /* T4: rpath blocks openat(O_WRONLY) via argument filter */
    run_test("rpath_openat_wronly_blocked", "stdio rpath",
             child_openat_wronly, 1);

    /* T5: wpath allows openat(O_WRONLY) unconditionally */
    run_test("wpath_openat_wronly", "stdio wpath",
             child_openat_wronly_ok, 0);

    /* T6: inet allows socket(AF_INET) via argument filter */
    run_test("inet_socket_allowed", "stdio inet",
             child_socket_inet, 0);

    /* T7: inet blocks socket(AF_UNIX) via argument filter */
    run_test("inet_socket_unix_blocked", "stdio inet",
             child_socket_unix, 1);

    /* T8: stdio blocks socket entirely */
    run_test("stdio_socket_blocked", "stdio",
             child_socket_any, 1);

    /* T9: proc allows clone/fork */
    run_test("proc_fork_allowed", "stdio proc",
             child_clone_fork, 0);

    /* T10: stdio blocks clone/fork */
    run_test("stdio_fork_blocked", "stdio",
             child_clone_attempt, 1);

    /* T11: empty pledge blocks write */
    run_test("empty_pledge_blocks_write", "",
             child_write_blocked, 1);

    /* T12: empty pledge still allows exit_group */
    run_test("empty_pledge_allows_exit", "",
             child_exit_only, 0);

    printf("\n=== Results: %d passed, %d failed ===\n", g_passed, g_failed);

    unlink("/tmp/pledge_test_file");
    return g_failed > 0 ? 1 : 0;
}
