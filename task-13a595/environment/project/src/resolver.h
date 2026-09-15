#ifndef NETMON_RESOLVER_H
#define NETMON_RESOLVER_H

#include <stddef.h>

int resolve_hostname(const char *hostname, char *ip_buf, size_t buf_len);

#endif /* NETMON_RESOLVER_H */
