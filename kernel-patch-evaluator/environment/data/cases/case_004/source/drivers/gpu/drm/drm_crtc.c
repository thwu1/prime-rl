// SPDX-License-Identifier: GPL-2.0
/*
 * DRM CRTC initialization and management.
 */

#include <drm/drm_crtc.h>
#include <drm/drm_mode.h>
#include <linux/slab.h>

#define DRM_MAX_CRTCS 16

/*
 * Initialize a CRTC structure.
 */
int drm_crtc_init(struct drm_device *dev,
                  struct drm_crtc *crtc,
                  const struct drm_crtc_funcs *funcs)
{
    if (!dev || !crtc || !funcs)
        return -EINVAL;

    crtc->dev = dev;
    crtc->funcs = funcs;
    crtc->enabled = false;
    crtc->dpms_mode = DRM_MODE_DPMS_OFF;
    crtc->num_connectors = 0;
    memset(&crtc->mode, 0, sizeof(crtc->mode));

    return 0;
}

/*
 * Destroy a CRTC and free resources.
 */
void drm_crtc_cleanup(struct drm_crtc *crtc)
{
    if (!crtc)
        return;

    crtc->enabled = false;
    crtc->funcs = NULL;
    crtc->dev = NULL;
}

/*
 * Set DPMS power mode.
 */
int drm_crtc_set_dpms(struct drm_crtc *crtc, int dpms_mode)
{
    if (!crtc)
        return -EINVAL;

    if (dpms_mode < DRM_MODE_DPMS_ON || dpms_mode > DRM_MODE_DPMS_OFF)
        return -EINVAL;

    crtc->dpms_mode = dpms_mode;
    return 0;
}
