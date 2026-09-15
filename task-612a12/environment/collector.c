#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <signal.h>
#include <time.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>

/*
 * Metrics collector daemon.
 *
 * Connects to local services using a simple length-prefixed binary protocol:
 *   - 4 bytes: payload length (network byte order, big-endian)
 *   - N bytes: JSON payload
 *
 * Polls each configured endpoint every POLL_INTERVAL seconds and logs
 * the collected data.
 */


#define DEFAULT_CONFIG_PATH "/app/config/endpoints.conf"
#define LOG_PATH "/var/log/collector/collector.log"
#define MAX_ENDPOINTS 16
#define POLL_INTERVAL 5
#define RECV_TIMEOUT_SEC 5

typedef struct {
    char name[64];
    char host[64];
    int port;
} endpoint_t;

static endpoint_t endpoints[MAX_ENDPOINTS];
static int num_endpoints = 0;
static FILE *logfp = NULL;
static volatile int running = 1;

static void handle_signal(int sig) {
    (void)sig;
    running = 0;
}

static void log_msg(const char *fmt, ...) {
    if (!logfp) return;

    time_t now = time(NULL);
    struct tm *tm = localtime(&now);
    char timebuf[64];
    strftime(timebuf, sizeof(timebuf), "%Y-%m-%d %H:%M:%S", tm);

    fprintf(logfp, "[%s] ", timebuf);

    va_list ap;
    va_start(ap, fmt);
    vfprintf(logfp, fmt, ap);
    va_end(ap);

    fprintf(logfp, "\n");
}

static int load_config(const char *path) {
    FILE *fp = fopen(path, "r");
    if (!fp) {
        fprintf(stderr, "Cannot open config: %s: %s\n", path, strerror(errno));
        return -1;
    }

    char line[256];
    num_endpoints = 0;

    while (fgets(line, sizeof(line), fp) && num_endpoints < MAX_ENDPOINTS) {
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '#' || *p == '\n' || *p == '\0') continue;

        endpoint_t *ep = &endpoints[num_endpoints];
        if (sscanf(p, "%63s %63s %d", ep->name, ep->host, &ep->port) == 3) {
            num_endpoints++;
        }
    }

    fclose(fp);
    return num_endpoints;
}

static int collect_from(endpoint_t *ep) {
    int sock;
    struct sockaddr_in addr;
    struct timeval tv;
    uint32_t msg_len;
    int n;

    sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) {
        log_msg("socket() failed for %s: %s", ep->name, strerror(errno));
        return -1;
    }

    /* Set receive timeout */
    tv.tv_sec = RECV_TIMEOUT_SEC;
    tv.tv_usec = 0;
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(ep->port);
    inet_pton(AF_INET, ep->host, &addr.sin_addr);

    if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        log_msg("connect to %s (%s:%d) failed: %s",
                ep->name, ep->host, ep->port, strerror(errno));
        close(sock);
        return -1;
    }

    log_msg("polling %s at %s:%d", ep->name, ep->host, ep->port);

    /* Read 4-byte length prefix (network byte order) */
    n = recv(sock, &msg_len, sizeof(msg_len), MSG_WAITALL);
    if (n != sizeof(msg_len)) {
        log_msg("Failed to read header from %s:%d (got %d bytes)",
                ep->host, ep->port, n);
        close(sock);
        return -1;
    }

    msg_len = ntohl(msg_len);
    log_msg("Service %s reports payload size: %u bytes", ep->name, msg_len);

    /* Allocate buffer for payload */
    char *buf = (char *)malloc(msg_len);
    if (!buf) {
        log_msg("Failed to allocate %u bytes for %s", msg_len, ep->name);
        close(sock);
        return -1;
    }

    /* Read the payload */
    int total = 0;
    while (total < (int)msg_len) {
        n = recv(sock, buf + total, msg_len - total, 0);
        if (n <= 0) {
            log_msg("Truncated data from %s: got %d of %u bytes",
                    ep->name, total, msg_len);
            return -1;
        }
        total += n;
    }

    log_msg("Collected %d bytes from %s", total, ep->name);

    free(buf);
    close(sock);
    return 0;
}

int main(int argc, char **argv) {
    const char *config_path = (argc > 1) ? argv[1] : DEFAULT_CONFIG_PATH;

    signal(SIGTERM, handle_signal);
    signal(SIGINT, handle_signal);
    signal(SIGPIPE, SIG_IGN);

    logfp = fopen(LOG_PATH, "a");
    if (!logfp) {
        logfp = stderr;
    }

    log_msg("collector started, loading config from %s", config_path);

    int count = load_config(config_path);
    if (count <= 0) {
        log_msg("No endpoints loaded, exiting");
        return 1;
    }

    log_msg("loaded %d endpoints", count);

    while (running) {
        for (int i = 0; i < num_endpoints && running; i++) {
            collect_from(&endpoints[i]);
        }

        if (running) {
            sleep(POLL_INTERVAL);
        }
    }

    log_msg("collector shutting down");
    if (logfp != stderr) fclose(logfp);
    return 0;
}
