#ifndef NETMON_API_H
#define NETMON_API_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

const char* netmon_version(void);
int netmon_check_host(const char *hostname);
int netmon_get_local_hostname(char *buf, size_t len);
void netmon_print_info(void);

#ifdef __cplusplus
}
#endif

#endif /* NETMON_API_H */
