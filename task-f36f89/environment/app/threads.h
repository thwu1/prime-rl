#ifndef THREADS_H
#define THREADS_H

#define MAX_TASKS   8
#define STACK_SIZE  1024    /* 32-bit words per thread stack (4096 bytes) */

/*
 * Create a new thread that will execute func(arg).
 * Returns thread ID (>= 0) on success, -1 on failure.
 */
int thread_create(void (*func)(void *), void *arg);

/*
 * Start the threading system and transfer control to the first thread.
 * This function does not return.
 */
void thread_start(void);

/*
 * Terminate a thread and free its stack memory.
 */
void thread_kill(int thread_id);

#endif
