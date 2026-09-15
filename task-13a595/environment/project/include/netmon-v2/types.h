#ifndef NETMON_TYPES_H
#define NETMON_TYPES_H

typedef enum {
    NETMON_STATUS_OK = 0,
    NETMON_STATUS_ERROR = -1,
    NETMON_STATUS_TIMEOUT = -2,
    NETMON_STATUS_UNREACHABLE = -3
} netmon_status_t;

typedef struct {
    char hostname[256];
    char ip_address[64];
    int port;
    netmon_status_t status;
    double latency_ms;
} netmon_result_t;

#endif /* NETMON_TYPES_H */
