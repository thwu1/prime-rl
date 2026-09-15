/*
 * ptysession - PTY session manager
 * Usage: ptysession <command> [args...]
 *
 * Creates an isolated PTY-backed terminal session for the given command.
 * Provides bidirectional I/O relay and signal forwarding.
 *
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>

static volatile pid_t g_child = 0;

static void sig_forward(int sig)
{
    pid_t p = g_child;
    if (p > 0)
        kill(-p, sig);
}

static int pty_open(int *sfd_out)
{
    int mfd = posix_openpt(O_RDWR | O_NOCTTY);
    if (mfd < 0)
        return -1;

    /* Prevent master FD from leaking into exec'd children */
    if (fcntl(mfd, F_SETFD, FD_CLOEXEC) < 0 ||
        grantpt(mfd) < 0 || unlockpt(mfd) < 0) {
        close(mfd);
        return -1;
    }

    char *sname = ptsname(mfd);
    if (!sname) {
        close(mfd);
        return -1;
    }

    int sfd = open(sname, O_RDWR | O_NOCTTY);
    if (sfd < 0) {
        close(mfd);
        return -1;
    }

    *sfd_out = sfd;
    return mfd;
}

static int child_setup(int sfd)
{
    /* Create a new session — this process becomes session leader */
    if (setsid() < 0)
        return -1;

    /* Acquire the PTY slave as the controlling terminal */
    if (ioctl(sfd, TIOCSCTTY, 0) < 0)
        return -1;

    /* Set usable terminal dimensions */
    struct winsize ws = { .ws_row = 24, .ws_col = 80 };
    ioctl(sfd, TIOCSWINSZ, &ws);

    /* Wire stdin/stdout/stderr to the PTY slave */
    if (dup2(sfd, STDIN_FILENO) < 0)
        return -1;
    if (dup2(sfd, STDOUT_FILENO) < 0)
        return -1;
    if (dup2(sfd, STDERR_FILENO) < 0)
        return -1;
    if (sfd > STDERR_FILENO)
        close(sfd);

    /* Restore default signal disposition for the child */
    signal(SIGTERM, SIG_DFL);
    signal(SIGINT, SIG_DFL);

    return 0;
}

static void io_loop(int mfd)
{
    struct pollfd pf[2];
    int nfd = 2;
    char buf[4096];
    ssize_t n;

    pf[0].fd = mfd;
    pf[0].events = POLLIN;
    pf[1].fd = STDIN_FILENO;
    pf[1].events = POLLIN;

    for (;;) {
        if (poll(pf, nfd, -1) < 0) {
            if (errno == EINTR)
                continue;
            break;
        }

        /* PTY master -> parent stdout (relay child output) */
        if (pf[0].revents & (POLLIN | POLLHUP | POLLERR)) {
            n = read(mfd, buf, sizeof buf);
            if (n <= 0)
                break;
            write(STDOUT_FILENO, buf, n);
        }

        /* Parent stdin -> PTY master (forward input to child) */
        if (nfd > 1 && (pf[1].revents & (POLLIN | POLLHUP | POLLERR))) {
            n = read(STDIN_FILENO, buf, sizeof buf);
            if (n <= 0) {
                /* Stdin exhausted — stop polling it */
                nfd = 1;
            } else {
                write(mfd, buf, n);
            }
        }
    }
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s command [args...]\n", argv[0]);
        return 1;
    }

    int sfd;
    int mfd = pty_open(&sfd);
    if (mfd < 0) {
        perror("pty_open");
        return 1;
    }

    /* Install signal handlers before fork so no window exists
     * where signals would use default (terminate) behavior */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = sig_forward;
    sa.sa_flags = SA_RESTART;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);

    pid_t pid = fork();
    if (pid < 0) {
        perror("fork");
        return 1;
    }

    if (pid == 0) {
        /* Child: master is not needed (and has CLOEXEC anyway) */
        close(mfd);
        if (child_setup(sfd) < 0)
            _exit(1);
        execvp(argv[1], argv + 1);
        perror("execvp");
        _exit(127);
    }

    /* Parent */
    g_child = pid;

    /* Release the slave so the master sees EOF when the child exits.
     * Without this, the slave's reference count stays positive and
     * read() on the master blocks indefinitely after child death. */
    close(sfd);

    io_loop(mfd);
    close(mfd);

    int st;
    waitpid(pid, &st, 0);
    if (WIFEXITED(st))
        return WEXITSTATUS(st);
    if (WIFSIGNALED(st))
        return 128 + WTERMSIG(st);
    return 1;
}
