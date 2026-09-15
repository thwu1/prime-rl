/*
 * reporter - print process session and terminal properties
 *
 * Outputs key=value pairs describing the calling process's
 * PID, session, process group, controlling terminal, open
 * file descriptors, and terminal window geometry.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <termios.h>

int main(void)
{
    printf("PID=%d\n", getpid());
    printf("PPID=%d\n", getppid());
    printf("SID=%d\n", getsid(0));
    printf("PGID=%d\n", getpgrp());

    int ctty = open("/dev/tty", O_RDWR | O_NOCTTY);
    if (ctty >= 0) {
        printf("HAS_CTTY=yes\n");
        close(ctty);
    } else {
        printf("HAS_CTTY=no\n");
    }

    char *tname = ttyname(STDIN_FILENO);
    printf("STDIN_TTY=%s\n", tname ? tname : "none");

    pid_t fg = tcgetpgrp(STDIN_FILENO);
    printf("FGPG=%d\n", fg);

    int fdc = 0;
    for (int i = 0; i < 1024; i++) {
        if (fcntl(i, F_GETFD) >= 0)
            fdc++;
    }
    printf("FD_COUNT=%d\n", fdc);

    struct winsize ws = {0, 0, 0, 0};
    ioctl(STDIN_FILENO, TIOCGWINSZ, &ws);
    printf("ROWS=%d\n", ws.ws_row);
    printf("COLS=%d\n", ws.ws_col);

    fflush(stdout);
    return 0;
}
