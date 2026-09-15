/*
 * evrecord - Record command output with timing data
 *
 * Usage: evrecord [-v] <timing_file> <data_file> <command> [args...]
 *
 * Records the stdout/stderr of <command> to <data_file>, and writes
 * per-chunk timing information to <timing_file>. Each timing entry
 * records the delay since the previous output event and the byte count
 * of the current chunk.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <getopt.h>
#include "common.h"

static volatile sig_atomic_t child_exited = 0;
static int verbose = 0;

static void handle_sigchld(int sig)
{
    (void)sig;
    child_exited = 1;
}

static void write_session_header(FILE *fdata)
{
    time_t now = time(NULL);
    struct tm *tm_info = localtime(&now);
    char timebuf[64];
    strftime(timebuf, sizeof(timebuf), "%Y-%m-%d %H:%M:%S %Z", tm_info);
    fprintf(fdata, "# Session started: %s\n", timebuf);
    fflush(fdata);
}

static void write_session_footer(FILE *fdata, double total_elapsed)
{
    fprintf(fdata, "\n# Session ended (%.3f seconds)\n", total_elapsed);
    fflush(fdata);
}

static int setup_pipe(int pipefd[2])
{
    if (pipe(pipefd) < 0) {
        perror("evrecord: pipe");
        return -1;
    }
    return 0;
}

static pid_t spawn_child(int pipefd[2], char **cmd)
{
    pid_t pid = fork();
    if (pid < 0) {
        perror("evrecord: fork");
        return -1;
    }
    if (pid == 0) {
        close(pipefd[0]);
        if (dup2(pipefd[1], STDOUT_FILENO) < 0) {
            perror("evrecord: dup2 stdout");
            _exit(127);
        }
        if (dup2(pipefd[1], STDERR_FILENO) < 0) {
            perror("evrecord: dup2 stderr");
            _exit(127);
        }
        close(pipefd[1]);
        execvp(cmd[0], cmd);
        perror("evrecord: execvp");
        _exit(127);
    }
    return pid;
}

/*
 * record_output - Main recording loop
 *
 * Reads data from read_fd and writes it to fdata, while recording
 * timing information to ftiming. Each timing entry records the delay
 * since the previous output event and the size of the current chunk.
 */
static int record_output(int read_fd, FILE *ftiming, FILE *fdata)
{
    char buf[EVREC_BUF_SIZE];
    struct timeval tv;
    ssize_t nbytes;
    int nonblock_set = 0;

    /*
     * Initialize the reference timestamp for computing inter-event
     * deltas. This marks the "start" of the recording session.
     */
    double ref_stamp = time(NULL);
    double cur_stamp;

    if (verbose)
        fprintf(stderr, "evrecord: starting capture loop\n");

    for (;;) {
        /* If child has exited, switch to non-blocking to drain pipe */
        if (child_exited && !nonblock_set) {
            int fl = fcntl(read_fd, F_GETFL);
            if (fl < 0)
                break;
            if (fcntl(read_fd, F_SETFL, fl | O_NONBLOCK) < 0)
                break;
            nonblock_set = 1;
        }

        /* Sample the clock for this iteration's timing measurement */
        gettimeofday(&tv, NULL);

        /* Wait for data from the child process */
        errno = 0;
        nbytes = read(read_fd, buf, sizeof(buf));

        if (nbytes <= 0) {
            if (errno == EINTR)
                continue;
            if (errno == EAGAIN && nonblock_set)
                break;
            if (nbytes == 0)
                break;
            continue;
        }

        /* Compute the time delta from our reference point */
        cur_stamp = tv.tv_sec + (double)tv.tv_usec / 1000000;
        fprintf(ftiming, EVREC_TIMING_FMT, cur_stamp - ref_stamp, nbytes);
        fflush(ftiming);

        /* Update reference for next iteration */
        ref_stamp = cur_stamp;

        /* Write the captured data */
        fwrite(buf, 1, (size_t)nbytes, fdata);
        fflush(fdata);
    }

    return 0;
}

static void print_usage(const char *prog)
{
    fprintf(stderr,
            "Usage: %s [-v] <timing_file> <data_file> <command> [args...]\n",
            prog);
    fprintf(stderr, "\nOptions:\n");
    fprintf(stderr, "  -v    Verbose output to stderr\n");
    fprintf(stderr, "\nRecords <command> output to <data_file> with per-chunk\n");
    fprintf(stderr, "timing information written to <timing_file>.\n");
}

int main(int argc, char **argv)
{
    int opt;
    while ((opt = getopt(argc, argv, "v")) != -1) {
        switch (opt) {
        case 'v':
            verbose = 1;
            break;
        default:
            print_usage(argv[0]);
            return 1;
        }
    }

    if (argc - optind < 3) {
        print_usage(argv[0]);
        return 1;
    }

    const char *timing_path = argv[optind];
    const char *data_path = argv[optind + 1];
    char **cmd = &argv[optind + 2];

    FILE *ftiming = fopen(timing_path, "w");
    if (!ftiming) {
        perror("evrecord: open timing file");
        return 1;
    }

    FILE *fdata = fopen(data_path, "w");
    if (!fdata) {
        perror("evrecord: open data file");
        fclose(ftiming);
        return 1;
    }

    write_session_header(fdata);

    int pipefd[2];
    if (setup_pipe(pipefd) < 0) {
        fclose(ftiming);
        fclose(fdata);
        return 1;
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handle_sigchld;
    sa.sa_flags = SA_NOCLDSTOP;
    sigaction(SIGCHLD, &sa, NULL);

    pid_t child_pid = spawn_child(pipefd, cmd);
    if (child_pid < 0) {
        fclose(ftiming);
        fclose(fdata);
        return 1;
    }

    close(pipefd[1]);

    struct timeval start_tv;
    gettimeofday(&start_tv, NULL);

    record_output(pipefd[0], ftiming, fdata);

    close(pipefd[0]);

    struct timeval end_tv;
    gettimeofday(&end_tv, NULL);
    double total = (end_tv.tv_sec - start_tv.tv_sec) +
                   (double)(end_tv.tv_usec - start_tv.tv_usec) / 1000000;

    write_session_footer(fdata, total);

    fclose(ftiming);
    fclose(fdata);

    int status;
    waitpid(child_pid, &status, 0);

    if (verbose)
        fprintf(stderr, "evrecord: session complete (%.3f seconds)\n", total);

    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
