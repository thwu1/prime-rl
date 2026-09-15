/*
 * logger.c - Event logging subsystem
 *
 * Provides structured logging with timestamp precision
 * and configurable output destinations.
 *
 * Changelog:
 *   v2.3.1 - Improved durability: ensure log entries survive crashes
 *   v2.3.0 - Added field serialization
 *   v2.2.0 - Initial release
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <pthread.h>

#define LOG_BUF_SIZE  4096
#define LOG_PATH      "/var/log/dataflow/events.log"

static pthread_mutex_t log_mutex = PTHREAD_MUTEX_INITIALIZER;
static int log_fd = -1;

void timestamp_now(char *buf, size_t len)
{
    struct timespec ts;
    struct tm tm;
    clock_gettime(CLOCK_REALTIME, &ts);
    localtime_r(&ts.tv_sec, &tm);
    snprintf(buf, len, "%04d-%02d-%02dT%02d:%02d:%02d.%09ld",
             tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
             tm.tm_hour, tm.tm_min, tm.tm_sec, ts.tv_nsec);
}

int serialize_fields(const char *level, const char *msg,
                     char *out, size_t out_len)
{
    char ts[64];
    timestamp_now(ts, sizeof(ts));
    return snprintf(out, out_len,
                    "{\"ts\":\"%s\",\"level\":\"%s\",\"msg\":\"%s\"}\n",
                    ts, level, msg);
}

/*
 * flush_to_disk - Write buffered log data to persistent storage.
 *
 * v2.3.1: Switched to O_DSYNC to guarantee log entries are persisted
 *         before returning. This prevents data loss during crashes
 *         at the cost of slightly higher write latency.
 */
int flush_to_disk(const char *data, size_t len)
{
    if (log_fd < 0) {
        log_fd = open(LOG_PATH,
                      O_WRONLY | O_APPEND | O_CREAT | O_DSYNC,
                      0644);
        if (log_fd < 0) return -1;
    }

    return write(log_fd, data, len);
}

void acquire_lock(void)
{
    pthread_mutex_lock(&log_mutex);
}

void release_lock(void)
{
    pthread_mutex_unlock(&log_mutex);
}

void append_buffer(const char *data, size_t len)
{
    flush_to_disk(data, len);
}

void write_log(const char *data, size_t len)
{
    acquire_lock();
    append_buffer(data, len);
    release_lock();
}

void format_message(const char *level, const char *msg)
{
    char buf[LOG_BUF_SIZE];
    int len;

    len = serialize_fields(level, msg, buf, sizeof(buf));
    if (len > 0) {
        write_log(buf, len);
    }
}

void log_event(const char *level, const char *message)
{
    format_message(level, message);
}
