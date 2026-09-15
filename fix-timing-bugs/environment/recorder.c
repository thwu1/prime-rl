/*
 * recorder.c - Session I/O recorder with timing metadata
 *
 * Captures stdout/stderr from a subprocess and produces two output files:
 *
 *   Data file:   Raw bytes from the subprocess output, written sequentially.
 *
 *   Timing file: One header comment line followed by timing entries.
 *                Each entry is a line containing two fields: the elapsed
 *                time (in seconds, floating-point) since the previous
 *                chunk, and the number of bytes in this chunk.  The first
 *                entry records elapsed time since recording began.
 *
 * Usage: recorder [-d datafile] [-t timingfile] [-q] [--] command [args...]
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/time.h>
#include <time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <signal.h>
#include <errno.h>
#include <fcntl.h>

#define IO_BUFSIZ      4096
#define DEFAULT_DATA   "recording.dat"
#define DEFAULT_TIMING "recording.tim"

static volatile sig_atomic_t child_exited = 0;
static int opt_quiet = 0;

/* ------------------------------------------------------------------ */
/*  Signal handlers                                                    */
/* ------------------------------------------------------------------ */

static void on_sigchld(int sig) {
    (void)sig;
    child_exited = 1;
}

static void on_sigpipe(int sig) {
    (void)sig;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s [options] [--] command [args...]\n\n"
        "  -d FILE   Output data file    (default: %s)\n"
        "  -t FILE   Output timing file  (default: %s)\n"
        "  -q        Quiet mode\n"
        "  -h        Show this help message\n",
        prog, DEFAULT_DATA, DEFAULT_TIMING);
}

/*
 * write_timing_header - emit a header comment into the timing file.
 * Consumers must skip lines beginning with '#'.
 */
static void write_timing_header(FILE *ftiming, const char *cmd) {
    time_t now = time(NULL);
    struct tm *info = localtime(&now);
    char buf[64];
    strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", info);
    fprintf(ftiming, "# recorder v1.0 ts=%s cmd=%s\n", buf, cmd);
    fflush(ftiming);
}

/*
 * make_nonblocking - set O_NONBLOCK on a file descriptor.
 * Returns 0 on success, -1 on failure.
 */
static int make_nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL);
    if (flags == -1)
        return -1;
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

/*
 * write_timing_entry - append one delay+size record to the timing file.
 */
static void write_timing_entry(FILE *ftiming, double delay, ssize_t nbytes) {
    fprintf(ftiming, "%f %zd\n", delay, nbytes);
    fflush(ftiming);
}

/* ------------------------------------------------------------------ */
/*  Core recording logic                                               */
/* ------------------------------------------------------------------ */

/*
 * capture_output - read from pipe_fd, writing raw data to fdata and
 * per-chunk timing information to ftiming.
 *
 * The recording starts by sampling the current time.  For each chunk
 * read from the pipe, the elapsed time since the previous sample is
 * recorded alongside the byte count.  When the child process exits,
 * remaining pipe data is drained in non-blocking mode.
 */
static void capture_output(int pipe_fd, FILE *fdata, FILE *ftiming) {
    char buf[IO_BUFSIZ];
    struct timeval tv;
    double oldtime = time(NULL), newtime;
    ssize_t nread;
    int draining = 0;

    for (;;) {
        /* Switch to drain mode once we know the child has exited */
        if (child_exited && !draining) {
            make_nonblocking(pipe_fd);
            draining = 1;
        }

        /* Sample current time for delta calculation */
        gettimeofday(&tv, NULL);

        /* Read next chunk from the child process */
        errno = 0;
        nread = read(pipe_fd, buf, sizeof(buf));
        if (nread <= 0) {
            if (errno == EINTR)
                continue;
            if (draining && errno == EAGAIN)
                break;
            break;
        }

        /* Compute elapsed time and write timing entry */
        newtime = tv.tv_sec + (double) tv.tv_usec / 1000000;
        write_timing_entry(ftiming, newtime - oldtime, nread);
        oldtime = newtime;

        /* Write raw output data */
        fwrite(buf, 1, nread, fdata);
        fflush(fdata);
    }
}

/* ------------------------------------------------------------------ */
/*  Entry point                                                        */
/* ------------------------------------------------------------------ */

int main(int argc, char **argv) {
    const char *data_path = DEFAULT_DATA;
    const char *timing_path = DEFAULT_TIMING;
    int opt, pipefd[2];
    pid_t child;
    int status;
    FILE *fdata, *ftiming;
    struct sigaction sa;

    while ((opt = getopt(argc, argv, "+d:t:qh")) != -1) {
        switch (opt) {
        case 'd': data_path = optarg; break;
        case 't': timing_path = optarg; break;
        case 'q': opt_quiet = 1; break;
        case 'h': usage(argv[0]); return 0;
        default:  usage(argv[0]); return 1;
        }
    }

    if (optind >= argc) {
        fprintf(stderr, "%s: no command specified\n", argv[0]);
        usage(argv[0]);
        return 1;
    }

    if (pipe(pipefd) == -1) {
        perror("pipe");
        return 1;
    }

    /* Install signal handlers */
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_sigchld;
    sa.sa_flags = SA_RESTART | SA_NOCLDSTOP;
    sigaction(SIGCHLD, &sa, NULL);

    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_sigpipe;
    sa.sa_flags = SA_RESTART;
    sigaction(SIGPIPE, &sa, NULL);

    child = fork();
    if (child == -1) {
        perror("fork");
        return 1;
    }

    if (child == 0) {
        /* Child: redirect stdout/stderr to pipe and exec the command */
        close(pipefd[0]);
        dup2(pipefd[1], STDOUT_FILENO);
        dup2(pipefd[1], STDERR_FILENO);
        close(pipefd[1]);
        execvp(argv[optind], &argv[optind]);
        perror("execvp");
        _exit(127);
    }

    /* Parent: set up output files and record */
    close(pipefd[1]);

    fdata = fopen(data_path, "wb");
    if (!fdata) {
        perror(data_path);
        kill(child, SIGTERM);
        return 1;
    }

    ftiming = fopen(timing_path, "w");
    if (!ftiming) {
        perror(timing_path);
        fclose(fdata);
        kill(child, SIGTERM);
        return 1;
    }

    write_timing_header(ftiming, argv[optind]);

    if (!opt_quiet)
        fprintf(stderr, "Recording session (data=%s, timing=%s)...\n",
                data_path, timing_path);

    capture_output(pipefd[0], fdata, ftiming);

    close(pipefd[0]);
    waitpid(child, &status, 0);
    fclose(fdata);
    fclose(ftiming);

    if (!opt_quiet)
        fprintf(stderr, "Recording complete.\n");

    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
