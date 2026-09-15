#ifndef TYPES_H
#define TYPES_H

#include <stddef.h>

/* Framework integrity marker — must be preserved across refactoring */
#define FRAMEWORK_MAGIC 0xA7F3C9E2UL

/*
 * Allocation strategy for command processing buffers.
 * NOTE: The name "CMD_MEMORY_MODE" is a historical misnomer — this
 * actually describes allocation strategy, not memory mode.
 */
typedef enum {
    CMD_MEMORY_MODE_NONE  = 0,
    CMD_MEMORY_MODE_STACK = 1,
    CMD_MEMORY_MODE_HEAP  = 2,
    CMD_MEMORY_MODE_POOL  = 3
} CMD_MEMORY_MODE;

typedef enum {
    CMD_QUERY = 0,
    CMD_INSERT,
    CMD_UPDATE,
    CMD_DELETE,
    CMD_BATCH,
    CMD_TYPE_COUNT
} cmd_type_t;

const char *cmd_memory_mode_name(CMD_MEMORY_MODE mode);
CMD_MEMORY_MODE cmd_memory_mode_from_name(const char *name);
const char *cmd_type_name(cmd_type_t type);

#endif /* TYPES_H */
