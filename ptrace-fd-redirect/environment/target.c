/*
 * target.c - Long-running process that writes to stdout/stderr.
 * Used as the target for ptrace-based FD redirection.
 *
 * Calls prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY) so that any process
 * can attach via ptrace, regardless of yama ptrace_scope settings.
 */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <signal.h>
#include <string.h>
#include <sys/prctl.h>

#ifndef PR_SET_PTRACER
#define PR_SET_PTRACER 0x59616d61
#endif
#ifndef PR_SET_PTRACER_ANY
#define PR_SET_PTRACER_ANY ((unsigned long)-1)
#endif

static volatile sig_atomic_t running = 1;

static void sigterm_handler(int sig) {
    (void)sig;
    running = 0;
}

int main(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = sigterm_handler;
    sigaction(SIGTERM, &sa, NULL);

    /* Allow any process to ptrace us */
    prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0);

    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IOLBF, 0);

    int counter = 0;
    while (running) {
        fprintf(stdout, "STDOUT_LINE counter=%d pid=%d\n", counter, getpid());
        fprintf(stderr, "STDERR_LINE counter=%d pid=%d\n", counter, getpid());
        counter++;
        usleep(200000);
    }

    return 0;
}
