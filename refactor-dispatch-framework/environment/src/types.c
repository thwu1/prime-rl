#include "types.h"
#include <string.h>

static const char *memory_mode_names[] = {
    "none", "stack", "heap", "pool"
};

const char *cmd_memory_mode_name(CMD_MEMORY_MODE mode) {
    if (mode >= 0 && mode <= CMD_MEMORY_MODE_POOL)
        return memory_mode_names[mode];
    return "unknown";
}

CMD_MEMORY_MODE cmd_memory_mode_from_name(const char *name) {
    for (int i = 0; i <= CMD_MEMORY_MODE_POOL; i++) {
        if (strcmp(name, memory_mode_names[i]) == 0)
            return (CMD_MEMORY_MODE)i;
    }
    return CMD_MEMORY_MODE_NONE;
}

const char *cmd_type_name(cmd_type_t type) {
    static const char *names[] = {
        "query", "insert", "update", "delete", "batch"
    };
    if (type >= 0 && type < CMD_TYPE_COUNT)
        return names[type];
    return "unknown";
}
