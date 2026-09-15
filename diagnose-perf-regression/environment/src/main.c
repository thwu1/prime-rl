/*
 * main.c - Dataflow application entry point
 *
 * Initializes subsystems and runs the main event loop.
 *
 * Changelog:
 *   v2.3.1 - Updated dependencies
 *   v2.3.0 - Added cache management
 *   v2.2.0 - Initial release
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <signal.h>
#include <sys/epoll.h>

#define MAX_EVENTS 64

/* Forward declarations */
extern void handle_requests(int server_fd, const char *data, size_t data_len);
extern void load_data(const char *source_path);
extern void transform(const char *record, size_t len);
extern void manage_cache(void);
extern void log_event(const char *level, const char *message);

static volatile int running = 1;

void signal_handler(int sig)
{
    (void)sig;
    running = 0;
}

int epoll_wait_loop(int epfd, struct epoll_event *events, int maxevents)
{
    return epoll_wait(epfd, events, maxevents, 1000);
}

void idle(int epfd)
{
    struct epoll_event events[MAX_EVENTS];
    epoll_wait_loop(epfd, events, MAX_EVENTS);
}

int main(int argc, char *argv[])
{
    int epfd;
    const char *data_source = "/var/lib/dataflow/input";

    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    log_event("INFO", "dataflow v2.3.1 starting");

    epfd = epoll_create1(0);
    if (epfd < 0) {
        log_event("ERROR", "epoll_create1 failed");
        return 1;
    }

    load_data(data_source);

    while (running) {
        handle_requests(epfd, NULL, 0);
        manage_cache();
        idle(epfd);
    }

    log_event("INFO", "dataflow shutting down");
    close(epfd);
    return 0;
}
