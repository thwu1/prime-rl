/*
 */
#ifndef TYPES_H
#define TYPES_H

#include <stdint.h>

typedef enum {
    STATE_INVALID = 0,
    STATE_SHARED,
    STATE_EXCLUSIVE,
    STATE_MODIFIED
} LineState;

static inline const char *state_name(LineState s) {
    switch (s) {
        case STATE_INVALID:   return "I";
        case STATE_SHARED:    return "S";
        case STATE_EXCLUSIVE: return "E";
        case STATE_MODIFIED:  return "M";
        default:              return "?";
    }
}

#endif /* TYPES_H */
