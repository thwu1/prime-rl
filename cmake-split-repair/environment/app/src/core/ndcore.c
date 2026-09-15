#include "ndcore.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

static char version_buf[64];

/* Internal: parse a key=value pair from a config line */
int parse_config_value(const char *line, const char *key,
                       char *out, size_t out_len) {
    if (!line || !key || !out) return -1;
    const char *p = strstr(line, key);
    if (!p) return -1;
    p += strlen(key);
    while (*p == ' ' || *p == '=' || *p == '\t') p++;
    size_t i = 0;
    while (*p && *p != '\n' && *p != '\r' && i < out_len - 1) {
        out[i++] = *p++;
    }
    out[i] = '\0';
    return 0;
}

/* Internal: restore factory-default configuration */
void reset_config_defaults(nd_config_t *cfg) {
    if (!cfg) return;
    free(cfg->bind_address);
    free(cfg->config_path);
    cfg->bind_address = strdup("0.0.0.0");
    cfg->port = 8443;
    cfg->max_connections = 128;
    cfg->config_path = strdup("/etc/netdaemon/netdaemon.conf");
    cfg->log_level = 1;
}

int nd_config_init(nd_config_t *cfg) {
    if (!cfg) return -1;
    cfg->bind_address = strdup("127.0.0.1");
    cfg->port = 8443;
    cfg->max_connections = 256;
    cfg->config_path = strdup("/etc/netdaemon/netdaemon.conf");
    cfg->log_level = 2;
    return 0;
}

void nd_config_free(nd_config_t *cfg) {
    if (!cfg) return;
    free(cfg->bind_address);
    free(cfg->config_path);
}

int nd_config_load(nd_config_t *cfg, const char *path) {
    if (!cfg || !path) return -1;
    free(cfg->config_path);
    cfg->config_path = strdup(path);
    FILE *fp = fopen(path, "r");
    if (fp) {
        char line[256], val[128];
        while (fgets(line, sizeof(line), fp)) {
            if (parse_config_value(line, "port", val, sizeof(val)) == 0) {
                cfg->port = atoi(val);
            }
            if (parse_config_value(line, "bind", val, sizeof(val)) == 0) {
                free(cfg->bind_address);
                cfg->bind_address = strdup(val);
            }
        }
        fclose(fp);
    } else {
        reset_config_defaults(cfg);
    }
    return 0;
}

void nd_log(int level, const char *fmt, ...) {
    if (level < 0) return;
    va_list args;
    va_start(args, fmt);
    fprintf(stderr, "[nd:%d] ", level);
    vfprintf(stderr, fmt, args);
    fprintf(stderr, "\n");
    va_end(args);
}

const char *nd_version_string(void) {
    snprintf(version_buf, sizeof(version_buf), "%d.%d.%d",
             ND_VERSION_MAJOR, ND_VERSION_MINOR, ND_VERSION_PATCH);
    return version_buf;
}
