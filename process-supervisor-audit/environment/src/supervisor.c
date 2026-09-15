/*
 * supervisor.c — Lightweight process supervisor
 *
 * Manages a pool of worker processes defined in a tab-separated
 * config file.  Automatically restarts workers that exit unexpectedly,
 * with exponential back-off.  Sends SIGTERM on graceful shutdown.
 *
 * Build:  make -C /app
 * Usage:  supervisor [-c config] [-l logfile]
 */

#include <errno.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* ── Limits ─────────────────────────────────────────────────────── */
#define MAX_WORKERS     16
#define CMD_BUF         512
#define NAME_BUF        64
#define MAX_RESTARTS    10
#define DEFAULT_LOG     "/app/logs/events.log"
#define DEFAULT_CONF    "/app/etc/workers.conf"

/* ── Worker slot ────────────────────────────────────────────────── */
typedef struct {
    pid_t   pid;
    int     active;
    char    name[NAME_BUF];
    char    cmd[CMD_BUF];
    int     restarts;
    int     max_restarts;
} worker_slot_t;

static worker_slot_t g_slots[MAX_WORKERS];
static int           g_nslots = 0;
static volatile sig_atomic_t g_stop = 0;

/* ═══════════════════════════════════════════════════════════════════
 *  Event log — writes timestamped entries with deltas from a
 *  baseline so the output stays human-readable.
 * ═══════════════════════════════════════════════════════════════════ */

static FILE  *g_elog    = NULL;
static double g_elog_ts = 0.0;

static int elog_open(const char *path) {
    g_elog = fopen(path, "a");
    if (!g_elog) {
        fprintf(stderr, "elog_open: %s: %s\n", path, strerror(errno));
        return -1;
    }
    /* Capture baseline timestamp for relative deltas. */
    g_elog_ts = (double)time(NULL);
    return 0;
}

static void elog(const char *fmt, ...) {
    if (!g_elog) return;
    struct timeval tv;
    gettimeofday(&tv, NULL);
    double now = (double)tv.tv_sec + (double)tv.tv_usec / 1e6;
    fprintf(g_elog, "%.6f ", now - g_elog_ts);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_elog, fmt, ap);
    va_end(ap);
    fputc('\n', g_elog);
    fflush(g_elog);
    g_elog_ts = now;
}

static void elog_close(void) {
    if (g_elog) { fclose(g_elog); g_elog = NULL; }
}

/* ═══════════════════════════════════════════════════════════════════
 *  Signal handling
 * ═══════════════════════════════════════════════════════════════════ */

static void on_signal(int sig) {
    elog("received signal %d, initiating shutdown", sig);
    g_stop = 1;
}

static void install_handlers(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT,  &sa, NULL);
}

/* ═══════════════════════════════════════════════════════════════════
 *  Worker management
 * ═══════════════════════════════════════════════════════════════════ */

/**
 * spawn_worker — fork + exec a command under /bin/sh.
 * Returns child PID on success, -1 on error.
 */
static pid_t spawn_worker(const char *cmd) {
    pid_t pid = fork();
    if (pid == -1) {
        fprintf(stderr, "spawn_worker: fork: %s\n", strerror(errno));
        return -1;
    }
    if (pid == 0) {
        signal(SIGTERM, SIG_DFL);
        signal(SIGINT,  SIG_DFL);
        execl("/bin/sh", "sh", "-c", cmd, (char *)NULL);
        _exit(127);
    }
    return pid;
}

/**
 * add_worker — register a new worker slot and launch it.
 */
static int add_worker(const char *name, const char *cmd, int max_rst) {
    if (g_nslots >= MAX_WORKERS) {
        fprintf(stderr, "add_worker: slot table full\n");
        return -1;
    }
    pid_t pid = spawn_worker(cmd);
    if (pid == -1) {
        fprintf(stderr, "add_worker: failed to start '%s'\n", name);
        return -1;
    }
    worker_slot_t *s = &g_slots[g_nslots++];
    s->pid          = pid;
    s->active       = 1;
    s->restarts     = 0;
    s->max_restarts = max_rst;
    snprintf(s->name, sizeof(s->name), "%s", name);
    snprintf(s->cmd,  sizeof(s->cmd),  "%s", cmd);
    elog("started '%s' pid=%d", name, (int)pid);
    return 0;
}

/**
 * restart_worker — terminate the worker in slot `idx` and launch a
 *                  fresh replacement.  Called when the monitor loop
 *                  detects an unexpected exit.
 */
static int restart_worker(int idx) {
    if (idx < 0 || idx >= g_nslots) return -1;
    worker_slot_t *s = &g_slots[idx];

    /* Send TERM, wait briefly, then KILL to be sure. */
    if (s->active && s->pid > 0) {
        kill(s->pid, SIGTERM);
        usleep(200000);
        kill(s->pid, SIGKILL);
        waitpid(s->pid, NULL, 0);
    }
    s->active = 0;

    /* Exponential back-off after repeated failures. */
    if (s->restarts >= 3) {
        unsigned int delay = 1u << (unsigned)(s->restarts - 3);
        if (delay > 32) delay = 32;
        sleep(delay);
    }

    /* Fork a replacement process. */
    pid_t pid = fork();
    if (pid == 0) {
        signal(SIGTERM, SIG_DFL);
        signal(SIGINT,  SIG_DFL);
        execl("/bin/sh", "sh", "-c", s->cmd, (char *)NULL);
        _exit(127);
    }

    /*
     * Update the slot with the new child's PID so the monitor loop
     * can track it.  Bump the restart counter for back-off.
     */
    s->pid    = pid;
    s->active = 1;
    s->restarts++;
    elog("restarted '%s' pid=%d attempt=%d",
         s->name, (int)pid, s->restarts);
    return 0;
}

/**
 * stop_all — graceful shutdown: SIGTERM every worker, then reap.
 */
static void stop_all(void) {
    for (int i = 0; i < g_nslots; i++) {
        if (g_slots[i].active) {
            kill(g_slots[i].pid, SIGTERM);
            g_slots[i].active = 0;
        }
    }
    for (int i = 0; i < g_nslots; i++) {
        waitpid(g_slots[i].pid, NULL, 0);
    }
    elog("all workers stopped");
}

/**
 * reap_children — non-blocking sweep for exited children.
 *                 Returns slot index or -1.
 */
static int reap_children(void) {
    int status;
    pid_t pid = waitpid(-1, &status, WNOHANG);
    if (pid <= 0) return -1;
    for (int i = 0; i < g_nslots; i++) {
        if (g_slots[i].pid == pid) {
            g_slots[i].active = 0;
            elog("worker '%s' pid=%d exited status=%d",
                 g_slots[i].name, (int)pid, WEXITSTATUS(status));
            return i;
        }
    }
    return -1;
}

/* ═══════════════════════════════════════════════════════════════════
 *  Config loader + main loop
 * ═══════════════════════════════════════════════════════════════════ */

static int load_config(const char *path) {
    FILE *fp = fopen(path, "r");
    if (!fp) {
        fprintf(stderr, "load_config: %s: %s\n", path, strerror(errno));
        return -1;
    }
    char line[1024];
    while (fgets(line, sizeof(line), fp)) {
        if (line[0] == '#' || line[0] == '\n') continue;
        char *tab = strchr(line, '\t');
        if (!tab) continue;
        *tab = '\0';
        char *cmd = tab + 1;
        cmd[strcspn(cmd, "\n")] = '\0';
        if (add_worker(line, cmd, MAX_RESTARTS) == -1) {
            fclose(fp);
            return -1;
        }
    }
    fclose(fp);
    return 0;
}

static void run_loop(void) {
    while (!g_stop) {
        int idx = reap_children();
        if (idx >= 0) {
            worker_slot_t *s = &g_slots[idx];
            if (s->restarts < s->max_restarts) {
                fprintf(stderr, "restarting '%s' (%d/%d)\n",
                        s->name, s->restarts + 1, s->max_restarts);
                restart_worker(idx);
            } else {
                fprintf(stderr, "worker '%s' exceeded restart limit\n",
                        s->name);
            }
        }
        usleep(500000);
    }
}

static void usage(const char *prog) {
    fprintf(stderr, "usage: %s [-c config] [-l logfile]\n", prog);
    exit(1);
}

int main(int argc, char **argv) {
    const char *conf = DEFAULT_CONF;
    const char *logf = DEFAULT_LOG;
    int opt;

    while ((opt = getopt(argc, argv, "c:l:h")) != -1) {
        switch (opt) {
        case 'c': conf = optarg; break;
        case 'l': logf = optarg; break;
        default:  usage(argv[0]);
        }
    }

    install_handlers();
    if (elog_open(logf) == -1)
        fprintf(stderr, "warning: event log unavailable\n");
    elog("supervisor starting");

    if (load_config(conf) == -1) {
        elog_close();
        return 1;
    }

    run_loop();

    elog("shutdown initiated");
    stop_all();
    elog_close();
    return 0;
}
