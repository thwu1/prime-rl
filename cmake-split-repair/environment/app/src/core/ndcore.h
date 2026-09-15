#ifndef NDCORE_H
#define NDCORE_H

#include <stddef.h>

#define ND_VERSION_MAJOR 3
#define ND_VERSION_MINOR 0
#define ND_VERSION_PATCH 0

typedef struct {
    char *bind_address;
    int port;
    int max_connections;
    char *config_path;
    int log_level;
} nd_config_t;

/* Initialize config with defaults */
int nd_config_init(nd_config_t *cfg);

/* Free config resources */
void nd_config_free(nd_config_t *cfg);

/* Load config from file path */
int nd_config_load(nd_config_t *cfg, const char *path);

/* Log a message at the given level */
void nd_log(int level, const char *fmt, ...);

/* Return version string "X.Y.Z" */
const char *nd_version_string(void);

#endif /* NDCORE_H */
