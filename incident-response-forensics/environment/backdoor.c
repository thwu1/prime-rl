
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>

/* Service identification markers */
static const char VERSION[] = "CACHE_SVC_v2.1";
static const char UA_STRING[] = "Mozilla/5.0 SystemUpdater/2.1";
static const char MUTEX_NAME[] = "cache_update_mtx";
static const int BEACON_INTERVAL = 300;

/* XOR key for encrypted configuration strings */
static const unsigned char XKEY[4] = {0x5A, 0x3C, 0x7E, 0x1D};

/* XOR-encrypted: "192.0.2.100" (secondary C2 IP) */
static const unsigned char ENC_C2_IP[] = {
    0x6B, 0x05, 0x4C, 0x33, 0x6A, 0x12, 0x4C, 0x33,
    0x6B, 0x0C, 0x4E
};
#define ENC_C2_IP_LEN 11

/* XOR-encrypted: "8443" (secondary C2 port) */
static const unsigned char ENC_C2_PORT[] = {
    0x62, 0x08, 0x4A, 0x2E
};
#define ENC_C2_PORT_LEN 4

/* XOR-encrypted: "updates-cdn.example.net" (DNS exfil domain) */
static const unsigned char ENC_DOMAIN[] = {
    0x2F, 0x4C, 0x1A, 0x7C, 0x2E, 0x59, 0x0D, 0x30,
    0x39, 0x58, 0x10, 0x33, 0x3F, 0x44, 0x1F, 0x70,
    0x2A, 0x50, 0x1B, 0x33, 0x34, 0x59, 0x0A
};
#define ENC_DOMAIN_LEN 23

static void xor_decode(unsigned char *dst, const unsigned char *src,
                       int len, const unsigned char *key, int keylen) {
    int i;
    for (i = 0; i < len; i++) {
        dst[i] = src[i] ^ key[i % keylen];
    }
}

int main(int argc, char *argv[]) {
    char c2_ip[64];
    char c2_port[16];
    char domain[128];

    memset(c2_ip, 0, sizeof(c2_ip));
    memset(c2_port, 0, sizeof(c2_port));
    memset(domain, 0, sizeof(domain));

    xor_decode((unsigned char*)c2_ip, ENC_C2_IP, ENC_C2_IP_LEN, XKEY, 4);
    xor_decode((unsigned char*)c2_port, ENC_C2_PORT, ENC_C2_PORT_LEN, XKEY, 4);
    xor_decode((unsigned char*)domain, ENC_DOMAIN, ENC_DOMAIN_LEN, XKEY, 4);

    fprintf(stderr, "[%s] initializing beacon\n", VERSION);
    fprintf(stderr, "Target: %s:%s\n", c2_ip, c2_port);
    fprintf(stderr, "DNS channel: %s\n", domain);
    fprintf(stderr, "User-Agent: %s\n", UA_STRING);
    fprintf(stderr, "Mutex: %s\n", MUTEX_NAME);
    fprintf(stderr, "Interval: %d\n", BEACON_INTERVAL);

    while (1) {
        sleep(BEACON_INTERVAL);
    }

    return 0;
}
