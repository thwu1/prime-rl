/*
 * test_threads.c - Thread-safety test for the refactored record library
 *
 * Spawns 4 threads, each parsing and formatting records concurrently.
 * Detects corruption from global mutable state (static buffers, global errno).
 *
 */

#include "record.h"
#include <pthread.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#define NUM_THREADS 4
#define ITERATIONS  1000

static volatile int thread_failed = 0;
static pthread_mutex_t fail_mutex = PTHREAD_MUTEX_INITIALIZER;

static void mark_failed(void) {
    pthread_mutex_lock(&fail_mutex);
    thread_failed = 1;
    pthread_mutex_unlock(&fail_mutex);
}

/* Pre-serialized binary records (built once in main, read-only in threads) */
static uint8_t metric_buf[1024];
static size_t  metric_len;
static uint8_t log_buf[1024];
static size_t  log_len;
static uint8_t alert_buf[1024];
static size_t  alert_len;
static uint8_t trace_buf[1024];
static size_t  trace_len;

static int build_test_records(void) {
    rec_error_t err;
    record_t rec;

    /* Metric */
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_METRIC;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.metric.name, "thread.metric", sizeof(rec.data.metric.name));
    rec.data.metric.value = 42.0;
    rec.data.metric.sample_time = 1700000000000000ULL;
    memset(&err, 0, sizeof(err));
    metric_len = rec_serialize(&rec, metric_buf, sizeof(metric_buf), &err);
    if (metric_len == 0) { fprintf(stderr, "serialize metric: %s\n", err.message); return -1; }

    /* Log */
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_LOG;
    rec.header.timestamp_us = 1700000000000000ULL;
    rec.data.log.level = 1;
    strncpy(rec.data.log.source, "threadsrc", sizeof(rec.data.log.source));
    strncpy(rec.data.log.message, "thread test log message", sizeof(rec.data.log.message));
    memset(&err, 0, sizeof(err));
    log_len = rec_serialize(&rec, log_buf, sizeof(log_buf), &err);
    if (log_len == 0) { fprintf(stderr, "serialize log: %s\n", err.message); return -1; }

    /* Alert */
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_ALERT;
    rec.header.timestamp_us = 1700000000000000ULL;
    rec.data.alert.severity = 3;
    strncpy(rec.data.alert.rule, "thread_rule", sizeof(rec.data.alert.rule));
    strncpy(rec.data.alert.detail, "thread test alert", sizeof(rec.data.alert.detail));
    memset(&err, 0, sizeof(err));
    alert_len = rec_serialize(&rec, alert_buf, sizeof(alert_buf), &err);
    if (alert_len == 0) { fprintf(stderr, "serialize alert: %s\n", err.message); return -1; }

    /* Trace */
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = REC_MAGIC;
    rec.header.version = REC_VERSION;
    rec.header.type = REC_TRACE;
    rec.header.timestamp_us = 1700000000000000ULL;
    strncpy(rec.data.trace.trace_id, "trace_t", sizeof(rec.data.trace.trace_id));
    strncpy(rec.data.trace.span_id, "span_t", sizeof(rec.data.trace.span_id));
    strncpy(rec.data.trace.parent_id, "parent_t", sizeof(rec.data.trace.parent_id));
    strncpy(rec.data.trace.operation, "thread_op", sizeof(rec.data.trace.operation));
    rec.data.trace.duration_us = 9999;
    rec.data.trace.status = 0;
    memset(&err, 0, sizeof(err));
    trace_len = rec_serialize(&rec, trace_buf, sizeof(trace_buf), &err);
    if (trace_len == 0) { fprintf(stderr, "serialize trace: %s\n", err.message); return -1; }

    return 0;
}

struct thread_data {
    const uint8_t *buf;
    size_t         len;
    int            thread_id;
    const char    *expected_type;
};

static void *parse_worker(void *arg) {
    struct thread_data *td = (struct thread_data *)arg;
    rec_error_t err;
    record_t rec;

    for (int i = 0; i < ITERATIONS && !thread_failed; i++) {
        /* Parse valid data */
        memset(&err, 0, sizeof(err));
        memset(&rec, 0, sizeof(rec));
        int ret = rec_parse(td->buf, td->len, &rec, &err);
        if (ret != 0) {
            fprintf(stderr, "Thread %d iter %d: parse failed: %s\n",
                    td->thread_id, i, err.message);
            mark_failed();
            return NULL;
        }

        /* Format into thread-local buffer */
        char fmt[512];
        int fret = rec_format(&rec, fmt, sizeof(fmt));
        if (fret < 0) {
            fprintf(stderr, "Thread %d iter %d: format failed\n",
                    td->thread_id, i);
            mark_failed();
            return NULL;
        }

        /* Check format output contains expected type string */
        if (strstr(fmt, td->expected_type) == NULL) {
            fprintf(stderr, "Thread %d iter %d: format '%s' missing '%s'\n",
                    td->thread_id, i, fmt, td->expected_type);
            mark_failed();
            return NULL;
        }

        /* Parse deliberately invalid data — error must go to local err */
        uint8_t bad[4] = {0xFF, 0xFF, 0, 0};
        memset(&err, 0, sizeof(err));
        ret = rec_parse(bad, sizeof(bad), &rec, &err);
        if (ret == 0) {
            fprintf(stderr, "Thread %d iter %d: bad parse should have failed\n",
                    td->thread_id, i);
            mark_failed();
            return NULL;
        }
        if (err.code == 0) {
            fprintf(stderr, "Thread %d iter %d: err.code not set after bad parse\n",
                    td->thread_id, i);
            mark_failed();
            return NULL;
        }
    }
    return NULL;
}

int main(void) {
    printf("Thread safety test: %d threads x %d iterations\n",
           NUM_THREADS, ITERATIONS);

    if (build_test_records() != 0) {
        fprintf(stderr, "Failed to build test records\n");
        return 1;
    }

    struct thread_data td[NUM_THREADS] = {
        { metric_buf, metric_len, 0, "METRIC" },
        { log_buf,    log_len,    1, "LOG"    },
        { alert_buf,  alert_len,  2, "ALERT"  },
        { trace_buf,  trace_len,  3, "TRACE"  },
    };

    pthread_t threads[NUM_THREADS];
    for (int i = 0; i < NUM_THREADS; i++) {
        if (pthread_create(&threads[i], NULL, parse_worker, &td[i]) != 0) {
            fprintf(stderr, "Failed to create thread %d\n", i);
            return 1;
        }
    }

    for (int i = 0; i < NUM_THREADS; i++) {
        pthread_join(threads[i], NULL);
    }

    if (thread_failed) {
        fprintf(stderr, "THREAD SAFETY TEST FAILED\n");
        return 1;
    }

    printf("THREAD SAFETY TEST PASSED\n");
    return 0;
}
