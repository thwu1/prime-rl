#ifndef ICECOMPAT_H
#define ICECOMPAT_H

/* IceCompat - ICE protocol compatibility layer
 *
 * Provides a simplified interface for ICE (Interactive Connectivity
 * Establishment) protocol operations used in network traversal.
 */

typedef struct {
    int protocol_version;
    int features;
    unsigned int session_id;
} ice_compat_config_t;

static inline int ice_compat_init(ice_compat_config_t *config) {
    if (!config) return -1;
    config->protocol_version = 1;
    config->features = 0;
    config->session_id = 0;
    return 0;
}

static inline int ice_compat_set_feature(ice_compat_config_t *config, int feature) {
    if (!config) return -1;
    config->features |= feature;
    return 0;
}

#define ICE_FEATURE_STUN    0x01
#define ICE_FEATURE_TURN    0x02
#define ICE_FEATURE_RELAY   0x04

#endif /* ICECOMPAT_H */
