/*
 * sesrec - Terminal session recorder with timing (FIXED + ENHANCED)
 *
 * Records terminal session output and timing data for later replay
 * by sesplay. Supports two timing formats:
 *   v1: <delta_seconds> <byte_count> per line (legacy)
 *   v2: header + <absolute_monotonic_seconds> <byte_count> per line
 *
 * Usage: sesrec [-o typescript] [-T timingfile] [-f v1|v2] -c command
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/time.h>
#include <sys/ioctl.h>
#include <time.h>
#include <fcntl.h>
#include <errno.h>
#include <pty.h>
#include <signal.h>

#define SESREC_VERSION "1.0.0"
#define DEFAULT_TYPESCRIPT "typescript"
#define DEFAULT_TIMING "timing"
#define OBUF_SIZE 16384

#define FMT_V1 1
#define FMT_V2 2

static volatile sig_atomic_t child_died = 0;
static pid_t child_pid = -1;

static void handle_sigchld(int sig)
{
    (void)sig;
    child_died = 1;
}

static void handle_sigterm(int sig)
{
    (void)sig;
    if (child_pid > 0)
        kill(child_pid, SIGTERM);
}

static void write_header(FILE *fp, const char *command)
{
    time_t now = time(NULL);
    char tbuf[128];
    struct tm *tm = localtime(&now);
    strftime(tbuf, sizeof(tbuf), "%c", tm);
    fprintf(fp, "Script started on %s\n", tbuf);
    if (command)
        fprintf(fp, "Command: %s\n", command);
}

static void write_footer(FILE *fp)
{
    time_t now = time(NULL);
    char tbuf[128];
    struct tm *tm = localtime(&now);
    strftime(tbuf, sizeof(tbuf), "%c", tm);
    fprintf(fp, "\nScript done on %s\n", tbuf);
}

static void usage(const char *prog)
{
    fprintf(stderr,
        "Usage: %s [options] -c command\n"
        "Options:\n"
        "  -o FILE    Output typescript to FILE (default: %s)\n"
        "  -T FILE    Output timing data to FILE (default: %s)\n"
        "  -f FMT     Timing format: v1 (delta) or v2 (absolute monotonic, default)\n"
        "  -c CMD     Command to record\n"
        "  -q         Quiet mode (suppress start/done messages)\n"
        "  -V         Show version\n"
        "  -h         Show this help\n",
        prog, DEFAULT_TYPESCRIPT, DEFAULT_TIMING);
    exit(1);
}

static double clock_mono(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static int record_session(const char *ts_path, const char *tm_path,
                          const char *command, int quiet, int format)
{
    int master_fd;
    struct winsize ws = { .ws_row = 24, .ws_col = 80 };

    child_pid = forkpty(&master_fd, NULL, NULL, &ws);
    if (child_pid < 0) {
        perror("forkpty");
        return 1;
    }

    if (child_pid == 0) {
        /* Child process - execute the requested command */
        setenv("SESREC", "1", 1);
        execl("/bin/sh", "sh", "-c", command, (char *)NULL);
        perror("execl");
        _exit(127);
    }

    /* Parent process - capture and record output */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = handle_sigchld;
    sa.sa_flags = SA_RESTART;
    sigaction(SIGCHLD, &sa, NULL);

    sa.sa_handler = handle_sigterm;
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);

    FILE *fscript = fopen(ts_path, "w");
    if (!fscript) {
        perror(ts_path);
        kill(child_pid, SIGTERM);
        return 1;
    }

    FILE *ftiming = fopen(tm_path, "w");
    if (!ftiming) {
        perror(tm_path);
        fclose(fscript);
        kill(child_pid, SIGTERM);
        return 1;
    }

    if (!quiet)
        fprintf(stderr, "Session recording started, output file is %s\n",
                ts_path);

    write_header(fscript, command);

    /* Write v2 format header if applicable */
    if (format == FMT_V2)
        fprintf(ftiming, "# sesrec-timing v2 monotonic\n");

    char obuf[OBUF_SIZE];
    double oldtime, newtime;
    int drain_flags = 0;
    ssize_t bytes_read;

    /* Initialize baseline with monotonic clock (nanosecond precision) */
    oldtime = clock_mono();

    for (;;) {
        /* If child exited, switch to non-blocking to drain remaining data */
        if (child_died && drain_flags == 0) {
            int fl = fcntl(master_fd, F_GETFL);
            if (fl == -1)
                break;
            if (fcntl(master_fd, F_SETFL, fl | O_NONBLOCK) == -1)
                break;
            drain_flags = 1;
        }

        errno = 0;
        bytes_read = read(master_fd, obuf, sizeof(obuf));

        if (bytes_read < 0 && errno == EINTR)
            continue;
        if (bytes_read <= 0)
            break;

        /* Sample clock AFTER read returns — measures actual wait time */
        newtime = clock_mono();

        /* Emit timing record in the selected format */
        if (format == FMT_V2)
            fprintf(ftiming, "%.9f %zd\n", newtime, bytes_read);
        else
            fprintf(ftiming, "%.6f %zd\n", newtime - oldtime, bytes_read);

        oldtime = newtime;

        /* Write captured data to typescript and optionally to stdout */
        fwrite(obuf, 1, bytes_read, fscript);
        if (!quiet)
            fwrite(obuf, 1, bytes_read, stdout);

        fflush(fscript);
        fflush(ftiming);
    }

    write_footer(fscript);
    fclose(fscript);
    fclose(ftiming);
    close(master_fd);

    int status;
    waitpid(child_pid, &status, 0);

    if (!quiet)
        fprintf(stderr, "Session recording completed\n");

    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}

int main(int argc, char *argv[])
{
    const char *ts_path = DEFAULT_TYPESCRIPT;
    const char *tm_path = DEFAULT_TIMING;
    const char *command = NULL;
    int quiet = 0;
    int format = FMT_V2;  /* Default to v2 */
    int opt;

    while ((opt = getopt(argc, argv, "o:T:c:f:qVh")) != -1) {
        switch (opt) {
        case 'o':
            ts_path = optarg;
            break;
        case 'T':
            tm_path = optarg;
            break;
        case 'c':
            command = optarg;
            break;
        case 'f':
            if (strcmp(optarg, "v1") == 0)
                format = FMT_V1;
            else if (strcmp(optarg, "v2") == 0)
                format = FMT_V2;
            else {
                fprintf(stderr, "sesrec: unknown format '%s' (use v1 or v2)\n",
                        optarg);
                return 1;
            }
            break;
        case 'q':
            quiet = 1;
            break;
        case 'V':
            printf("sesrec %s\n", SESREC_VERSION);
            return 0;
        case 'h':
        default:
            usage(argv[0]);
        }
    }

    if (!command)
        usage(argv[0]);

    return record_session(ts_path, tm_path, command, quiet, format);
}
