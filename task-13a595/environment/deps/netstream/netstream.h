#ifndef NETSTREAM_H
#define NETSTREAM_H

#include "icecompat/icecompat.h"

/* NetStream - Network stream management library
 *
 * Provides stream abstractions on top of ICE-negotiated connections.
 */

typedef struct {
    ice_compat_config_t ice_config;
    int stream_id;
    int state;
} net_stream_t;

#define NETSTREAM_STATE_INIT       0
#define NETSTREAM_STATE_CONNECTING 1
#define NETSTREAM_STATE_CONNECTED  2
#define NETSTREAM_STATE_CLOSED     3

static inline int net_stream_init(net_stream_t *stream) {
    if (!stream) return -1;
    ice_compat_init(&stream->ice_config);
    stream->stream_id = 0;
    stream->state = NETSTREAM_STATE_INIT;
    return 0;
}

static inline int net_stream_get_state(const net_stream_t *stream) {
    if (!stream) return -1;
    return stream->state;
}

#endif /* NETSTREAM_H */
