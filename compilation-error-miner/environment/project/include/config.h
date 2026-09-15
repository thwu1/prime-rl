#ifndef CONFIG_H
#define CONFIG_H

#define MAX_BUFFER_SIZE 4096
#define DEFAULT_PORT 8080
#define ENGINE_VERSION "2.0.1"

struct GlobalConfig {
    int port;
    int max_connections;
    bool debug_mode;
};

extern GlobalConfig g_config;

#endif // CONFIG_H
