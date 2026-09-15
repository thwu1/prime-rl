"""WebGL 1.0 state validation engine.

"""

import math
from gl_constants import *
from state_types import FramebufferAttachment


class WebGLStateValidator:
    """WebGL 1.0 conformance state validator.

    Refer to /app/spec_reference.md for specification requirements.
    """

    def is_texture_complete(self, texture):
        """Return True if the texture is complete for sampling.

        Must handle TEXTURE_2D and TEXTURE_CUBE_MAP targets per
        GLES2 Section 3.7.10, with WebGL 1.0 NPOT restrictions.
        """
        raise NotImplementedError

    def check_framebuffer_status(self, fb):
        """Return the framebuffer completeness status constant.

        Must return one of the FRAMEBUFFER_* status constants.
        See GLES2 Section 4.4.5 for evaluation ordering requirements.
        """
        raise NotImplementedError

    def validate_draw_call(self, state):
        """Validate draw-call preconditions.

        Returns (is_valid: bool, error_code: int).
        See GLES2 Section 2.8 and WebGL Section 5.14.
        """
        raise NotImplementedError
