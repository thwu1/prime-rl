/*
 * ptysession - create PTY-backed terminal sessions (fixed)
 * Usage: ptysession <command> [args...]
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/ioctl.h>
#include <termios.h>

static int open_pty_pair(int *slave_out)
{
    int mfd = posix_openpt(O_RDWR | O_NOCTTY);
    if (mfd < 0)
        return -1;
    /* Prevent master from leaking into exec'd children */
    fcntl(mfd, F_SETFD, FD_CLOEXEC);
    if (grantpt(mfd) < 0 || unlockpt(mfd) < 0) {
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
    *slave_out = sfd;
    return mfd;
}

static int setup_child_env(int sfd)
{
    if (setsid() < 0) {
        perror("setsid");
        return -1;
    }

    /* Acquire the slave as our controlling terminal */
    if (ioctl(sfd, TIOCSCTTY, 0) < 0) {
        perror("TIOCSCTTY");
        return -1;
    }

    /* Set a usable window size */
    struct winsize ws = { .ws_row = 24, .ws_col = 80 };
    ioctl(sfd, TIOCSWINSZ, &ws);

    if (dup2(sfd, STDIN_FILENO) < 0)
        return -1;
    if (dup2(sfd, STDOUT_FILENO) < 0)
        return -1;
    if (dup2(sfd, STDERR_FILENO) < 0)
        return -1;
    if (sfd > STDERR_FILENO)
        close(sfd);

    return 0;
}

static void relay(int mfd)
{
    char buf[4096];
    ssize_t n;
    while ((n = read(mfd, buf, sizeof(buf))) > 0)
        write(STDOUT_FILENO, buf, n);
}

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s command [args...]\n", argv[0]);
        return 1;
    }

    int sfd;
    int mfd = open_pty_pair(&sfd);
    if (mfd < 0) {
        fprintf(stderr, "Failed to allocate PTY\n");
        return 1;
    }

    pid_t pid = fork();
    if (pid < 0) {
        perror("fork");
        return 1;
    }

    if (pid == 0) {
        if (setup_child_env(sfd) < 0)
            _exit(1);
        execvp(argv[1], argv + 1);
        perror("execvp");
        _exit(127);
    }

    /* Parent must release slave so master sees EOF when child exits */
    close(sfd);

    relay(mfd);
    close(mfd);

    int st;
    waitpid(pid, &st, 0);
    if (WIFEXITED(st))
        return WEXITSTATUS(st);
    if (WIFSIGNALED(st))
        return 128 + WTERMSIG(st);
    return 1;
}
