/*
 * Trace output buffer for recording HSM execution traces.
 */

#ifndef TRACE_H
#define TRACE_H

#define TRACE_BUF_SIZE 4096

extern char trace_buf[];

void BSP_display(const char *msg);
void trace_clear(void);
const char *trace_get(void);

#endif /* TRACE_H */
