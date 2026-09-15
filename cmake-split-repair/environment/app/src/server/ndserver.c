#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include "../core/ndcore.h"
#include "../crypto/ndcrypto.h"

static volatile int running = 1;

static void handle_signal(int sig) {
    (void)sig;
    running = 0;
}

int main(int argc, char *argv[]) {
    printf("netdaemon server v%s\n", nd_version_string());

    nd_config_t cfg;
    nd_config_init(&cfg);

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--config") == 0 && i + 1 < argc) {
            nd_config_load(&cfg, argv[++i]);
        } else if (strcmp(argv[i], "--port") == 0 && i + 1 < argc) {
            cfg.port = atoi(argv[++i]);
        }
    }

    nd_log(1, "Starting server on %s:%d (max_conn=%d)",
           cfg.bind_address, cfg.port, cfg.max_conn);

    signal(SIGTERM, handle_signal);
    signal(SIGINT, handle_signal);

    while (running) {
        running = 0;
    }

    nd_log(1, "Server shutting down");
    nd_config_free(&cfg);
    return 0;
}
