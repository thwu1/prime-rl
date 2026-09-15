#include "netmon-v2/api.h"
#include "generated_config.h"
#include "resolver.h"
#include <stdio.h>
#include <string.h>

const char* netmon_version(void) {
    return NETMON_VERSION_STRING;
}

int netmon_check_host(const char *hostname) {
    char ip[64];
    memset(ip, 0, sizeof(ip));
    return resolve_hostname(hostname, ip, sizeof(ip));
}

int netmon_get_local_hostname(char *buf, size_t len) {
    if (!buf || len == 0) return -1;
    return gethostname(buf, len);
}
