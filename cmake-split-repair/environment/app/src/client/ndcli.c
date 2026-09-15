#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../core/ndcore.h"
#include "../crypto/ndcrypto.h"

int main(int argc, char *argv[]) {
    printf("netdaemon client v%s\n", nd_version_string());

    nd_config_t cfg;
    nd_config_init(&cfg);

    printf("Max connections: %d\n", cfg.max_conn);
    printf("Server: %s:%d\n", cfg.bind_address, cfg.port);

    if (argc > 1 && strcmp(argv[1], "hash") == 0 && argc > 2) {
        char hash[65];
        if (nd_hash_password(argv[2], hash, sizeof(hash)) == 0) {
            printf("Hash: %s\n", hash);
        }
    }

    nd_log(2, "Client configured with max_conn=%d", cfg.max_conn);

    nd_config_free(&cfg);
    return 0;
}
