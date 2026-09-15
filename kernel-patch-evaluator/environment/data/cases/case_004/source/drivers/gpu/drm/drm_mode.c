// SPDX-License-Identifier: GPL-2.0
/*
 * DRM mode setting support.
 */

#include <drm/drm_mode.h>
#include <drm/drm_crtc.h>
#include <linux/export.h>

struct drm_display_mode {
    int hdisplay;
    int vdisplay;
    int htotal;
    int vtotal;
    unsigned int flags;
    int clock;
    char name[32];
};

/*
 * Validate a display mode against hardware constraints.
 */
int drm_mode_validate(struct drm_display_mode *mode)
{
    if (mode->hdisplay <= 0 || mode->vdisplay <= 0)
        return -EINVAL;
    if (mode->htotal < mode->hdisplay)
        return -EINVAL;
    if (mode->vtotal < mode->vdisplay)
        return -EINVAL;
    if (mode->clock <= 0)
        return -EINVAL;
    return 0;
}

/*
 * Set CRTC configuration.
 */
int drm_mode_setcrtc(struct drm_crtc *crtc,
                     struct drm_display_mode *mode,
                     struct drm_connector **connectors,
                     unsigned int num_connectors)
{
    int ret;
    unsigned int i;

    if (!crtc || !mode)
        return -EINVAL;

    ret = drm_mode_validate(mode);
    if (ret)
        return ret;

    /* WARN if we're trying to set a mode while DPMS is off */
    WARN_ON(crtc->dpms_mode != DRM_MODE_DPMS_ON);

    if (num_connectors > DRM_MAX_CONNECTORS) {
        return -EINVAL;
    }

    for (i = 0; i < num_connectors; i++) {
        if (!connectors[i])
            return -EINVAL;
    }

    crtc->mode = *mode;
    crtc->num_connectors = num_connectors;
    crtc->enabled = true;

    return 0;
}

/*
 * Get the current mode for a CRTC.
 */
int drm_mode_getcrtc(struct drm_crtc *crtc,
                     struct drm_display_mode *mode)
{
    if (!crtc || !mode)
        return -EINVAL;

    if (!crtc->enabled)
        return -ENODEV;

    *mode = crtc->mode;
    return 0;
}
