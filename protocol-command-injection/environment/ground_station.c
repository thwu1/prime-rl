/*
 * Ground Station Control Protocol (GSCP) Server
 * Custom binary protocol for satellite ground station C2.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdarg.h>
#include <stdint.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <signal.h>
#include <time.h>
#include <errno.h>

#define PORT 9090
#define MAGIC_HI 0x47
#define MAGIC_LO 0x53
#define PROTO_VER 0x02
#define MAX_PAYLOAD 4096

#define PKT_AUTH     0x01
#define PKT_TELEM    0x02
#define PKT_CMD      0x03
#define PKT_STATUS   0x04
#define PKT_PING     0x05

#define AUTH_NONE     0
#define AUTH_OPERATOR 1
#define AUTH_ADMIN    2

#define RESP_OK    0x00
#define RESP_ERR   0x01

static char g_flag[256] = "FLAG{default_ground_station_flag}";
static FILE *g_logfile = NULL;

void log_msg(const char *fmt, ...) {
    if (!g_logfile) return;
    va_list ap;
    time_t now = time(NULL);
    struct tm *tm_info = localtime(&now);
    char timebuf[64];
    strftime(timebuf, sizeof(timebuf), "%Y-%m-%d %H:%M:%S", tm_info);
    fprintf(g_logfile, "[%s] ", timebuf);
    va_start(ap, fmt);
    vfprintf(g_logfile, fmt, ap);
    va_end(ap);
    fprintf(g_logfile, "\n");
    fflush(g_logfile);
}

uint8_t compute_checksum(const uint8_t *data, size_t len) {
    uint8_t chk = 0;
    size_t i;
    for (i = 0; i < len; i++) {
        chk ^= data[i];
    }
    return chk;
}

int send_response(int sock, uint8_t type, uint8_t status,
                  const char *payload, uint16_t len) {
    uint8_t header[7];
    header[0] = MAGIC_HI;
    header[1] = MAGIC_LO;
    header[2] = PROTO_VER;
    header[3] = type;
    header[4] = status;
    header[5] = (len >> 8) & 0xFF;
    header[6] = len & 0xFF;

    if (send(sock, header, 7, 0) != 7) return -1;
    if (len > 0 && payload) {
        if (send(sock, payload, len, 0) != (ssize_t)len) return -1;
    }
    uint8_t chk = compute_checksum((const uint8_t *)payload, len);
    if (send(sock, &chk, 1, 0) != 1) return -1;
    return 0;
}

int recv_exact(int sock, void *buf, size_t n) {
    size_t total = 0;
    while (total < n) {
        ssize_t r = recv(sock, (uint8_t *)buf + total, n - total, 0);
        if (r <= 0) return -1;
        total += (size_t)r;
    }
    return 0;
}

void handle_auth(int sock, int *auth_level,
                 const uint8_t *payload, uint16_t len) {
    static const char *op_user = "operator";
    static const char *op_pass = "typhoon2026";
    static const char *adm_user = "admin";
    /* Admin password XOR-obfuscated with key 0x5A: Gr0und$t@t10n_Adm!n */
    static const unsigned char adm_pass_enc[] = {
        0x1D, 0x28, 0x6A, 0x2F, 0x34, 0x3E, 0x7E, 0x2E,
        0x1A, 0x2E, 0x6B, 0x6A, 0x34, 0x05, 0x1B, 0x3E,
        0x37, 0x7B, 0x34, 0x00
    };

    char buf[512];
    uint16_t slen = len;
    if (slen >= sizeof(buf)) slen = sizeof(buf) - 1;
    memcpy(buf, payload, slen);
    buf[slen] = '\0';

    char *colon = strchr(buf, ':');
    if (!colon) {
        send_response(sock, PKT_AUTH, RESP_ERR,
                      "ERR:INVALID_AUTH_FORMAT", 22);
        log_msg("AUTH FAIL: invalid format");
        return;
    }
    *colon = '\0';
    char *user = buf;
    char *pass = colon + 1;

    /* Check operator credentials */
    if (strcmp(user, op_user) == 0 && strcmp(pass, op_pass) == 0) {
        *auth_level = AUTH_OPERATOR;
        send_response(sock, PKT_AUTH, RESP_OK,
                      "AUTH_OK:OPERATOR", 16);
        log_msg("AUTH OK: operator");
        return;
    }

    /* Decode and check admin credentials */
    char adm_pass[64];
    int i;
    for (i = 0; adm_pass_enc[i] != 0; i++) {
        adm_pass[i] = (char)(adm_pass_enc[i] ^ 0x5A);
    }
    adm_pass[i] = '\0';

    if (strcmp(user, adm_user) == 0 && strcmp(pass, adm_pass) == 0) {
        *auth_level = AUTH_ADMIN;
        send_response(sock, PKT_AUTH, RESP_OK,
                      "AUTH_OK:ADMIN", 13);
        log_msg("AUTH OK: admin");
        return;
    }

    send_response(sock, PKT_AUTH, RESP_ERR,
                  "ERR:INVALID_CREDENTIALS", 23);
    log_msg("AUTH FAIL: user=%s", user);
}

void handle_telem(int sock, int auth_level,
                  const uint8_t *payload, uint16_t len) {
    if (auth_level < AUTH_OPERATOR) {
        send_response(sock, PKT_TELEM, RESP_ERR,
                      "ERR:AUTH_REQUIRED", 17);
        return;
    }

    char subsystem[256];
    uint16_t slen = len;
    if (slen >= sizeof(subsystem)) slen = sizeof(subsystem) - 1;
    memcpy(subsystem, payload, slen);
    subsystem[slen] = '\0';

    log_msg("TELEM query: subsystem='%s'", subsystem);

    /* Expose flag via environment for subsystem query subprocess */
    setenv("GS_SECRET", g_flag, 1);

    /* VULNERABLE: unsanitized subsystem name passed to shell */
    char cmd[512];
    snprintf(cmd, sizeof(cmd), "/app/telem_query %s 2>&1", subsystem);

    FILE *fp = popen(cmd, "r");
    if (!fp) {
        send_response(sock, PKT_TELEM, RESP_ERR,
                      "ERR:QUERY_FAILED", 16);
        return;
    }

    char result[MAX_PAYLOAD];
    size_t total = 0;
    while (total < sizeof(result) - 1) {
        size_t n = fread(result + total, 1, sizeof(result) - total - 1, fp);
        if (n == 0) break;
        total += n;
    }
    pclose(fp);

    send_response(sock, PKT_TELEM, RESP_OK, result, (uint16_t)total);
}

void handle_cmd(int sock, int auth_level,
                const uint8_t *payload, uint16_t len) {
    if (auth_level < AUTH_ADMIN) {
        send_response(sock, PKT_CMD, RESP_ERR,
                      "ERR:ADMIN_AUTH_REQUIRED", 22);
        return;
    }

    char cmdname[256];
    uint16_t slen = len;
    if (slen >= sizeof(cmdname)) slen = sizeof(cmdname) - 1;
    memcpy(cmdname, payload, slen);
    cmdname[slen] = '\0';

    log_msg("CMD: %s", cmdname);

    if (strcmp(cmdname, "reboot") == 0) {
        send_response(sock, PKT_CMD, RESP_OK,
                      "CMD_OK:REBOOT_SCHEDULED", 23);
    } else if (strcmp(cmdname, "selftest") == 0) {
        send_response(sock, PKT_CMD, RESP_OK,
                      "CMD_OK:SELFTEST_PASS", 20);
    } else if (strcmp(cmdname, "getflag") == 0) {
        send_response(sock, PKT_CMD, RESP_OK,
                      g_flag, (uint16_t)strlen(g_flag));
    } else {
        send_response(sock, PKT_CMD, RESP_ERR,
                      "ERR:UNKNOWN_COMMAND", 19);
    }
}

void handle_status(int sock) {
    const char *status =
        "GROUND_STATION v2.4.1 STATUS:OPERATIONAL "
        "UPTIME:4382h LINK:ACTIVE "
        "LAST_CONTACT:2026-05-28T14:22:01Z";
    send_response(sock, PKT_STATUS, RESP_OK,
                  status, (uint16_t)strlen(status));
}

void handle_ping(int sock) {
    send_response(sock, PKT_PING, RESP_OK, "PONG", 4);
}

void handle_client(int sock) {
    int auth_level = AUTH_NONE;

    while (1) {
        /* Request header: magic(2) + version(1) + type(1) + length(2) = 6 */
        uint8_t header[6];
        if (recv_exact(sock, header, 6) < 0) break;

        if (header[0] != MAGIC_HI || header[1] != MAGIC_LO) {
            send_response(sock, 0x00, RESP_ERR,
                          "ERR:BAD_MAGIC", 13);
            break;
        }

        if (header[2] != PROTO_VER) {
            send_response(sock, 0x00, RESP_ERR,
                          "ERR:BAD_VERSION", 15);
            break;
        }

        uint8_t type = header[3];
        uint16_t length = ((uint16_t)header[4] << 8) | header[5];

        if (length > MAX_PAYLOAD) {
            send_response(sock, type, RESP_ERR,
                          "ERR:PAYLOAD_TOO_LARGE", 21);
            break;
        }

        /* Read payload */
        uint8_t payload[MAX_PAYLOAD];
        if (length > 0) {
            if (recv_exact(sock, payload, length) < 0) break;
        }

        /* Read checksum byte */
        uint8_t recv_chk;
        if (recv_exact(sock, &recv_chk, 1) < 0) break;

        /* Validate XOR checksum over payload */
        uint8_t calc_chk = compute_checksum(payload, length);
        if (recv_chk != calc_chk) {
            send_response(sock, type, RESP_ERR,
                          "ERR:BAD_CHECKSUM", 16);
            continue;
        }

        switch (type) {
            case PKT_AUTH:
                handle_auth(sock, &auth_level, payload, length);
                break;
            case PKT_TELEM:
                handle_telem(sock, auth_level, payload, length);
                break;
            case PKT_CMD:
                handle_cmd(sock, auth_level, payload, length);
                break;
            case PKT_STATUS:
                handle_status(sock);
                break;
            case PKT_PING:
                handle_ping(sock);
                break;
            default:
                send_response(sock, type, RESP_ERR,
                              "ERR:UNKNOWN_TYPE", 16);
                break;
        }
    }

    close(sock);
}

void sigchld_handler(int sig) {
    (void)sig;
    int saved_errno = errno;
    while (waitpid(-1, NULL, WNOHANG) > 0);
    errno = saved_errno;
}

int main(void) {
    /* Read flag from file at startup */
    FILE *f = fopen("/app/secrets/flag.txt", "r");
    if (f) {
        if (fgets(g_flag, sizeof(g_flag), f)) {
            char *nl = strchr(g_flag, '\n');
            if (nl) *nl = '\0';
        }
        fclose(f);
    }

    g_logfile = fopen("/app/server.log", "a");
    log_msg("Ground Station server starting on port %d", PORT);

    /* Use sigaction with SA_RESTART to avoid EINTR on accept/read */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = sigchld_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_RESTART | SA_NOCLDSTOP;
    sigaction(SIGCHLD, &sa, NULL);

    signal(SIGPIPE, SIG_IGN);

    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
        perror("socket");
        return 1;
    }

    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(PORT);

    if (bind(server_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind");
        return 1;
    }

    if (listen(server_fd, 5) < 0) {
        perror("listen");
        return 1;
    }

    log_msg("Listening on port %d", PORT);

    while (1) {
        struct sockaddr_in client_addr;
        socklen_t client_len = sizeof(client_addr);
        int client_fd = accept(server_fd,
                               (struct sockaddr *)&client_addr,
                               &client_len);
        if (client_fd < 0) {
            if (errno == EINTR) continue;
            perror("accept");
            continue;
        }

        log_msg("Connection from %s:%d",
                inet_ntoa(client_addr.sin_addr),
                ntohs(client_addr.sin_port));

        pid_t pid = fork();
        if (pid == 0) {
            /* Child: reset SIGCHLD so popen/pclose work correctly */
            signal(SIGCHLD, SIG_DFL);
            close(server_fd);
            handle_client(client_fd);
            _exit(0);
        } else if (pid > 0) {
            close(client_fd);
        } else {
            perror("fork");
            close(client_fd);
        }
    }

    return 0;
}
