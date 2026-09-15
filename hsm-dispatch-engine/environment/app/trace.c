#include "trace.h"
#include <string.h>

char trace_buf[TRACE_BUF_SIZE];

void BSP_display(const char *msg) {
    size_t cur = strlen(trace_buf);
    size_t rem = TRACE_BUF_SIZE - cur - 1;
    size_t len = strlen(msg);
    if (len > rem) len = rem;
    memcpy(trace_buf + cur, msg, len);
    trace_buf[cur + len] = '\0';
}

void trace_clear(void) {
    trace_buf[0] = '\0';
}

const char *trace_get(void) {
    return trace_buf;
}
